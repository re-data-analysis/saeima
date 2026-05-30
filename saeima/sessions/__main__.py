from saeima.sessions.analysis import build_votes_cmd
from saeima.sessions.getter import cli

cli.add_command(build_votes_cmd)
cli()
