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


@click.group()
def main():
    pass


def parse_config_file(f):
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
    yaml_section = list(takewhile(lambda line: not line.startswith("###"), f))
    metadata = yaml.load("".join(yaml_section))
    metadata["filename"] = f.name
    examples = list()
    # We split the examples on an empty line using groupby (groupby splits everytime the key function changes)
    for k, g in groupby(f, lambda x: x.strip() == ""):
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

@main.command()
@click.argument("files", nargs=-1, type=click.File('r'))
@click.option("--index", default=-1)
@click.option("--fresh-timestamps/--no-fresh-timestamps", default=True)
def test(files, index, fresh_timestamps):
    for f in files:
        config = parse_config_file(f)

        # For each config file, generate the required configuration files for both filebeat and logstash

        # 1. Write logs:
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

        # First truncate
        with log_file_path.open("a+") as fs:
            fs.write(output)


@main.command()
@click.argument("files", nargs=-1, type=click.File('r'))
def make(files):
    for f in files:
        parse_config_file(f)


if __name__ == "__main__":
    main()

