import click
import yaml
from itertools import takewhile, groupby
from pathlib import Path
from subprocess import check_call
import subprocess
import shutil
import re
import time
from jinja2 import Environment, PackageLoader
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import elk_herder.resources
import os


@click.group()
def main():
    pass


def parse_config_file(path):
    """
    The config file is expected to start with a YAML section which ends with three hashtags (###).
    This section contains metadata for the file being parsed.

        description: Describes the file
        paths: Lists the file paths where the logs are expected to be
        decoding: TODO

    When these are encountered, the rest of the file is expected to be a list of log entries that act as en example for
    this type of log entries.

    Each line that starts with grok defines the grok pattern that the next non-empty lines should match.

    """
    with open(path) as fs:
        yaml_section = list(takewhile(lambda line: not line.startswith("###"), fs))
        metadata = yaml.load("".join(yaml_section))
        metadata["filename"] = fs.name
        examples = list()
        # We split the examples on an empty line using groupby (groupby splits everytime the key function changes)
        for k, g in groupby(fs, lambda x: x.strip() == ""):
            if not k:
                # Append if the key function returned false, i.e. we're in an example section
                examples.append(list(g))
        metadata["examples"] = examples
        # Add `app` as the default application name
        if "application" not in metadata:
            metadata["application"] = "app"
        return metadata

@main.command()
def run():
    """Runs the dev servers as docker containers. Temporary files are kept in ./obj"""
    module_path = Path(os.path.dirname(elk_herder.resources.__file__))
    obj_dir = Path("./obj")
    obj_dir.mkdir(exist_ok=True)
    obj_dir.joinpath("prospectors.d").mkdir(exist_ok=True)
    shutil.copy(module_path.joinpath("docker-compose.yml"), obj_dir)

    # Copy initial settings file for filebeat. This ensures that we're watching the default log file
    filebeat_config = module_path.joinpath("filebeat.yml")
    filebeat_config_target = obj_dir.joinpath("filebeat.yml")
    shutil.copy(filebeat_config, filebeat_config_target)

    os.chmod(filebeat_config_target, 0o644)
    shutil.copy(module_path.joinpath("logstash.conf"), obj_dir)

    try:
        check_call(["docker-compose", "up"], cwd=obj_dir)
    except subprocess.CalledProcessError:
        print()
        print("Unable to execute docker-compose. Make sure it's installed. There may be more information above.")

def replace_timestamp(find, replace, str):
    replace = time.strftime(replace)
    return re.sub(find, replace, str)

def get_log_examples(config, index, fresh_timestamps):
    examples = config["examples"]
    # Use nothing but the indexed example if specified
    if index != -1:
        examples = [examples[index]]

    # Flatten the examples
    log_lines = [item for sublist in examples for item in sublist]

    # 2. Apply mutations:
    log_lines_mutated = list()

    for line in log_lines:
        mutated = line
        # Apply fresh timestamps if applicable
        if "timestamp" in config and fresh_timestamps:
            timestamp = config["timestamp"]
            find = timestamp["find"]
            replace = timestamp["replace"]
            mutated = replace_timestamp(find, replace, line)
        log_lines_mutated.append(mutated)
    return "".join(log_lines_mutated)

def build_filebeat_config(*configs):
    """
    Builds the config file that's going into (by default) /etc/filebeat/conf.d/<application name>. Takes a list of
    elk-herder config files and groups them by application name. If there is no application name, the configuration
    will be grouped under `app`

    filebeat:
      prospectors:
        - type: log
          paths:
            - /var/log/httpd/clarity_ssl_error_log
            - /var/log/httpd/clarity_ssl_access_log
          tags:
            - "clarity"


        filebeat.inputs:
        - type: log
          paths:
            - /var/log/elk-herder/filebeat-watches-me.log
          {{ multiline_pattern }}
          {{ multiline_negate }}
          {{ multiline_match }}
        - type: log
          paths:
            - /var/log/elk-herder/filebeat-watches-me.log

  multiline.pattern: '^\d+-\d+-\d+ '
  multiline.negate: true
  multiline.match: after
    """
    config = configs[0]  # TODO!

    prospector = {
        "type": "log",
        "paths": config["paths"],
        "multiline.pattern": "^\d+-\d+-\d+ ",
        "multiline.negate": True,
        "multiline.match": "after"
    }

    return yaml.dump([prospector], default_flow_style=False)

def test_config(config, index, fresh_timestamps, truncate_logs, server):
    """
    Builds each config file required from the main config and then pushes it to either a remote server via ssh
    or to the local docker image.
    """



    obj_path = Path("./obj")
    filebeat_app_config_dir_path = obj_path.joinpath("prospectors.d")
    filebeat_app_config_dir_path.mkdir(exist_ok=True)

    # For each config file, generate the required configuration files for both filebeat and logstash

    # 1. Update pipeline configuration:

    # Build a new logstash.conf file and replace it if it has changed:
    if len(config["groks"]) != 1:
        raise NotImplementedError("TEMPORARY grok not exactly one")
    grok = config["groks"][0]
    grok_section = 'match => { "message" => "' + grok + '" }'
    grok_section = "\n".join(["grok {", grok_section, "}"])

    env = Environment(loader=PackageLoader('elk_herder', 'resources'))
    template = env.get_template('logstash.conf.j2')
    logstash_conf_path = obj_path.joinpath("logstash.conf")
    logstash_conf_new_content = template.render(grok=grok_section)
    logstash_conf_old_content = logstash_conf_path.read_text("utf-8")

    if logstash_conf_old_content != logstash_conf_new_content:
        logstash_conf_path.write_text(logstash_conf_new_content, "utf-8")

    output = get_log_examples(config, index, fresh_timestamps)

    # Output log examples to the filebeat container
    # TODO: Support ssh-ing too
    # TODO: hardcoded
    mkdir = ["docker", "exec", "--user", "root", "-i", "elk_herder_filebeat", "mkdir", "-p", "/opt/clarity-ext/logs"]
    print("creating dir...")
    subprocess.check_call(mkdir)

    cmd = ["docker", "exec", "--user", "root", "-i", "elk_herder_filebeat", "tee", "-a", "/opt/clarity-ext/logs/extensions.log"]
    docker_process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    docker_process.stdin.write(output.encode("utf-8"))
    #docker_process.kill()  # TODO!!!

    # Build the filebeat config
    filebeat_app_config = build_filebeat_config(config)
    filebeat_app_config_file_path = filebeat_app_config_dir_path.joinpath(config["application"] + ".yml")
    filebeat_app_config_file_path.write_text(filebeat_app_config)
    filebeat_app_config_file_path.chmod(0o700)

    if server:
        print(f"Writing logs to {server}")
        try:
            path = config["paths"][0]
            print(path)
        except IndexError:
            raise Exception("No path defined in the config file")
        # TODO: Allow the user to specify where each ELK config file is at
        cmd = ["ssh", server, "mkdir -p output/dir; cat - > output/dir/file.dat"]
        print(cmd)
        print("HERE!!!")
        #raise NotImplementedError()
    else:
        print("Writing log example log entries to filebeat-watches-me.log...")
        log_file_path = Path("obj/logs/filebeat-watches-me.log")
        mode = "a+" if not truncate_logs else "w"
        with log_file_path.open(mode) as fs:
            fs.write(output)

class Handler(FileSystemEventHandler):
    def __init__(self, path, index, fresh_timestamps, server):
        self.file_name = os.path.basename(path)
        self.path = path
        self.last_time = 0
        self.index = index
        self.fresh_timestamps = fresh_timestamps
        self.server = server

    def handle(self, truncate_logs=False):
        config = parse_config_file(self.path)
        test_config(config, self.index, self.fresh_timestamps, truncate_logs, self.server)

    def on_modified(self, event):
        import time
        current_time = time.time()
        delta = current_time - self.last_time
        if os.path.basename(event.src_path) == self.file_name:
            if delta >= 0.5:
                self.handle()
                self.last_time = current_time


@main.command()
@click.argument("file")
@click.option("--index", default=-1, help="Index of the log example that should be pushed, use -1 if all examples should be used.")
@click.option("--follow/--no-follow", default=False, help="Follow changes to the configuration file")
@click.option("--server", help="Server to push changes to (via SSH). If not specified, the changes will "
                          "only be reflected locally and can be seen in by running elk-herder run")
@click.option("--fresh-timestamps/--no-fresh-timestamps", default=True)
def test(file, index, fresh_timestamps, server, follow):
    handler = Handler(file, index, fresh_timestamps, server)

    if follow:
        # Handle the event once, then handle on each file change
        handler.handle()

        directory = os.path.dirname(file)
        if not directory:
            directory = "."
        observer = Observer()
        observer.schedule(handler, directory)
        observer.start()
        print(f"Observing {directory}")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        handler.handle()


def generate_single(local_path, remote_path, new_file_name, application, example_lines=100):
    force = True
    if os.path.exists(new_file_name) and not force:
        print(f"File {new_file_name} already exists")
        return

    config_section = {
        "application": application,
        "tags": [application],
        "description": "TODO",
        "paths": [remote_path],
        "groks":  ["%{GREEDYDATA:rest}"],
        # NOTE: The timestamp pattern is just an example. It might not be relevant
        "timestamp": {
            "find": r"\\d+-\\d+-\\d+ (\\d+):(\\d+):(\\d+)",
            "replace": "%Y-%m-%d %H:%M:%S"
        }
    }
    print(config_section)

    with open(new_file_name, "w") as target:
        target.write(yaml.dump(config_section, default_flow_style=False) + os.linesep)
        target.write("###" + os.linesep)
        with open(local_path) as source:
            for ix, line in enumerate(source):
                if ix == example_lines:
                    break
                target.write(line.rstrip() + os.linesep)



@main.command()
@click.argument("directory")
@click.option("--app", default="app", help="The application these config files belong to")
def generate(directory, app):
    """Generates elk-herder config files from all log files found in DIRECTORY"""
    directory = Path(directory)
    if not directory.is_dir():
        raise Exception(f"Path {directory} is not a directory")
    def files():
        for dirpath, _, filenames in os.walk(directory):
            for filename in filenames:
                yield os.path.relpath(os.path.join(dirpath, filename), directory)
    for rel_path in files():
        #generate_single(file_path)
        # Use the path to the file as the default name for the config, this can be changed by the user afterwards
        name = re.sub(r"\W", "_", rel_path)
        name = name + ".config"
        file_path = os.path.join(directory, rel_path)
        generate_single(file_path, "/" + rel_path, name, app)

@main.command()
@click.argument("files", nargs=-1, type=click.File('r'))
def make(files):
    raise NotImplementedError()


if __name__ == "__main__":
    main()

