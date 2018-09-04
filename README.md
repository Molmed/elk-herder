WORK IN PROGRESS!

This tool aims to simplify creating ELK configuration and logstash groks. The configuration can be tested interactively in docker containers.

Instead of writing configuration for each part, you write one configuration file per log source. This configuration file includes:

* Enough information to create all other required configuration files
* Examples for integration tests

# Setup:

Install the Python tool `elk-herder` in py3, e.g. (with conda):

    conda create -q --name elk-herder python=3
    source activate elk-herder
    pip install -e elk-herder

# Parsing logs

Start by executing the docker environment. It will run a filebeat client and a logstash server. Filebeat will start pushing logs to logstash.

The `filebeat` server will be checking the contents of this file:

    ./obj/logs/filebeat-watches-me.log

Whenever you make changes to this file, the parsed entries should pop up in the terminal where you're running the server.

You can check if everything works as expected by executing:

    echo "I'm logging here" > obj/logs/filebeat-watches-me.log

# Ensuring all logs are parsed correctly in production

If some log entries aren't parsed correctly in production, they will pop up in Kibana if you search for

    tags:_grokparsefailure

When you encounter such a log, add it to the configuration file for the application you're parsing for, fix the groks and finally run `elk-herder make`.
