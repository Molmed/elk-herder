WORK IN PROGRESS!

This tool aims to simplify creating ELK configuration and logstash groks.

Instead of writing individual pipelines (with groks) and filebeat configuration, configuration is written in a .config file with this format:

    # YAML section
    description:
    paths: <list of path globs>
    groks: <list of groks that match the examples>
    # optional timestamp replacement
    timestamp:
      find: <regex>
      replace: <timestamp format, understood by Python's time.strftime>
    ### Examples. Free text section which starts with three hashtags

    Here follow log entries examples, followed by an empty line

elk-herder knows how to parse this file into both translate these into separate filebeat and logstash config files (with `elk-herder make`), as well as how to run interactive "integration" tests on this (with `elk-herder test`).

# Setup:

Install the Python tool `elk-herder` in py3, e.g. (with conda):

    conda create -q --name elk-herder python=3
    source activate elk-herder
    pip install -e elk-herder

# Developing groks and other config

Start by executing the docker environment.

    elk-herder run

This will run a filebeat client and a logstash server. Filebeat will start pushing logs to logstash.

Your log parse output will appear in this terminal, so keep it around.

Now write a new configuration file, for now, we can use ./examples/pythonapp.log.config

    elk-herder test --follow --index 0 ./examples/pythonapp.log.config

This will test the first log example, which is an INFO message.

Now (in a third terminal) try to open `./examples/pythonapp.log.config` in a text editor and change that first example in some way. You should see it pop up in the window where you executed `elk-herder run`.

Finally, try to change the grok. This will take a bit longer, since logstash will restart.

Note that groks can be tested much faster, but this tool provides an integration test for the whole process, where you can change (eventually) other aspects too.


# Ensuring all logs are parsed correctly in production

If some log entries aren't parsed correctly in production because your examples don't cover that format, they will pop up in Kibana if you search for

    tags:_grokparsefailure

When you encounter such a log, you can add it to the configuration file for the application you're parsing for, fix the groks, test it and then run `elk-herder make` again. The tool has now generated the latest config files you will need to deploy to ELK to parse future logs correctly.

# Ideas:

* The tool should be able to compare the output of logstash to expected outputs.
* The interactive test mode should have more user friendly output

