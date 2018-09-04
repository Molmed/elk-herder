import click
import yaml
from itertools import takewhile
from pathlib import Path


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
    metadata["examples"] = list(f)
    metadata["filename"] = f.name
    return metadata


@main.command()
@click.argument("files", nargs=-1, type=click.File('r'))
def test(files):
    for f in files:
        config = parse_config_file(f)

        # For each config file, generate the required configuration files for both filebeat and logstash

        # 1. filebeat requires a list of files it's listening to
        #print(config.keys())
        #print(config["examples"])

        print("Writing log example log entries to filebeat-watches-me.log...")
        print(config["examples"])
        log_file_path = Path("obj/logs/filebeat-watches-me.log")
        with log_file_path.open("w") as fs:
            fs.write("".join(config["examples"]))



@main.command()
@click.argument("files", nargs=-1, type=click.File('r'))
def make(files):
    for f in files:
        parse_config_file(f)


if __name__ == "__main__":
    main()

