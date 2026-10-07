"""State-aware guide for an agent meeting cbi for the first time."""

NOT_INITIALISED = """\
# cbi: codebase inspector

cbi maps a git repository into a model you can query from the command line,
instead of listing directories and grepping. The model is one tree:

  workspace (the repo; submodules are nested workspaces)
    deployable (something that runs or ships: an app, a service, a CLI)
    package (a library, workspace member or agent skill)
      folder or module
        file
          class, function, method, component, test case

Nodes are linked by imports, calls, tests (test case to the code it
exercises), part-of, depends-on and doc mentions.

cbi never calls a model and never runs the repo's code. Work that needs
judgement, such as summarising files and confirming what the deployables
are, comes back to you as tasks with a JSON answer to submit.

All output goes in a hidden .cbi/ directory that ignores itself, so no
tracked file in the repo changes.

## This repo is not mapped yet

Run these from the repo root:

  cbi init    # create .cbi/ and write .cbi/ignore (edit it to skip data dirs)
  cbi scan    # map the repo; reports what it found and how many tasks wait

Then run `cbi prime` again. It will show the next step for the repo's
new state.

Every command has `--help` describing its inputs, output and exit codes.
"""


def run():
    print(NOT_INITIALISED, end="")
