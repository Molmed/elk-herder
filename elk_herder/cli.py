import click
import yaml
from itertools import takewhile, groupby
from pathlib import Path
from subprocess import check_call
import os
import subprocess
import shutil
import re
import time
from jinja2 import Environment, PackageLoader
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


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
        return metadata

@main.command()
def run():
    """Runs the dev servers as docker containers. Temporary files are kept in ./obj"""
    import elk_herder.resources
    module_path = Path(os.path.dirname(elk_herder.resources.__file__))
    obj_dir = Path("./obj")
    obj_dir.mkdir(exist_ok=True)
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


def test_config(config, index, fresh_timestamps, truncate_logs):
    obj_path = Path("./obj")

    # For each config file, generate the required configuration files for both filebeat and logstash

    # 1. Update pipeline configuration:

    # Build a new logstash.conf file and replace it if it has changed.
    # Either a 'groks' or 'filter' entry is required.
    # TODO: add support for multiple groks
    has_grok = "groks" in config and len(config["groks"]) == 1
    has_filter = "filter" in config

    if not has_grok and not has_filter:
        raise NotImplementedError("TEMPORARY Only one 'grok' or 'filter' entry allowed")

    filter_section = ''

    if has_filter:
        filter_section = config["filter"]

    if has_grok:
        # TODO: add support for multiple groks
        grok = config["groks"][0]
        grok_section = 'match => { "message" => "' + grok + '" }'
        filter_section = "\n".join(["grok {", grok_section, "}"])

    filter_section = 'filter {' + filter_section + '}'
    env = Environment(loader=PackageLoader('elk_herder', 'resources'))
    template = env.get_template('logstash.conf.j2')
    logstash_conf_path = obj_path.joinpath("logstash.conf")
    logstash_conf_new_content = template.render(filter=filter_section)
    logstash_conf_old_content = logstash_conf_path.read_text("utf-8")

    if logstash_conf_old_content != logstash_conf_new_content:
        logstash_conf_path.write_text(logstash_conf_new_content, "utf-8")

    # 2. Write logs:
    print("Writing log example log entries to filebeat-watches-me.log...")
    log_file_path = Path("obj/logs/filebeat-watches-me.log")

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
    output = "".join(log_lines_mutated)

    mode = "a+" if not truncate_logs else "w"
    with log_file_path.open(mode) as fs:
        fs.write(output)

class Handler(FileSystemEventHandler):
    def __init__(self, path, index, fresh_timestamps):
        self.file_name = os.path.basename(path)
        self.path = path
        self.last_time = 0
        self.index = index
        self.fresh_timestamps = fresh_timestamps

    def handle(self, truncate_logs=False):
        config = parse_config_file(self.path)
        test_config(config, self.index, self.fresh_timestamps, truncate_logs)

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
@click.option("--index", default=-1)
@click.option("--follow/--no-follow", default=False)
@click.option("--fresh-timestamps/--no-fresh-timestamps", default=True)
def test(file, index, fresh_timestamps, follow):
    handler = Handler(file, index, fresh_timestamps)

    if follow:
        # Handle the event once, then handle on each file change
        handler.handle()

        directory = os.path.dirname(file)
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


@main.command()
@click.argument("files", nargs=-1, type=click.File('r'))
def make(files):
    for f in files:
        parse_config_file(f)


if __name__ == "__main__":
    main()

