"""
main_loop.py

Two variants:

main_loop.Interactive()
main_loop.Batch()

They call CommandParser.ParseLogicalLine() and CommandEvaluator.ExecuteAndCatch().

Get rid of:

ParseWholeFile() -- needs to check the here doc.
"""
from __future__ import print_function

from _devbuild.gen.syntax_asdl import (
    command_t, command,
    parse_result__EmptyLine, parse_result__Eof, parse_result__Node
)
from core import error
from core import ui
from core import util
from core.pyerror import log
from osh import cmd_eval
from mycpp import mylib

from typing import Any, List, TYPE_CHECKING
if TYPE_CHECKING:
  from core.alloc import Arena
  from core.comp_ui import _IDisplay
  from core.ui import ErrorFormatter
  from osh.cmd_parse import CommandParser
  from osh.cmd_eval import CommandEvaluator
  from osh.prompt import UserPlugin

_ = log


if mylib.PYTHON:
  def Interactive(flag, cmd_ev, c_parser, display, prompt_plugin, errfmt):
    # type: (Any, CommandEvaluator, CommandParser, _IDisplay, UserPlugin, ErrorFormatter) -> int

    # TODO: Any could be _Attributes from frontend/args.py

    status = 0
    done = False
    while not done:
      # - This loop has a an odd structure because we want to do cleanup after
      # every 'break'.  (The ones without 'done = True' were 'continue')
      # - display.EraseLines() needs to be called BEFORE displaying anything, so
      # it appears in all branches.

      while True:  # ONLY EXECUTES ONCE
        prompt_plugin.Run()
        try:
          # may raise HistoryError or ParseError
          result = c_parser.ParseInteractiveLine()
          if isinstance(result, parse_result__EmptyLine):
            display.EraseLines()
            break  # quit shell
          elif isinstance(result, parse_result__Eof):
            display.EraseLines()
            done = True
            break  # quit shell
          elif isinstance(result, parse_result__Node):
            node = result.cmd
          else:
            raise AssertionError()

        except util.HistoryError as e:  # e.g. expansion failed
          # Where this happens:
          # for i in 1 2 3; do
          #   !invalid
          # done
          display.EraseLines()
          print(e.UserErrorString())
          break
        except error.Parse as e:
          display.EraseLines()
          errfmt.PrettyPrintError(e)
          # NOTE: This should set the status interactively!  Bash does this.
          status = 2
          break
        except KeyboardInterrupt:  # thrown by InteractiveLineReader._GetLine()
          # Here we must print a newline BEFORE EraseLines()
          print('^C')
          display.EraseLines()
          # http://www.tldp.org/LDP/abs/html/exitcodes.html
          # bash gives 130, dash gives 0, zsh gives 1.
          # Unless we SET cmd_ev.last_status, scripts see it, so don't bother now.
          break

        display.EraseLines()  # Clear candidates right before executing

        # to debug the slightly different interactive prasing
        if cmd_ev.exec_opts.noexec():
          ui.PrintAst(node, flag)
          break

        is_return, _ = cmd_ev.ExecuteAndCatch(node)

        status = cmd_ev.LastStatus()
        if is_return:
          done = True
          break

        break  # QUIT LOOP after one iteration.

      # Cleanup after every command (or failed command).

      # Reset internal newline state.
      c_parser.Reset()
      c_parser.ResetInputObjects()

      display.Reset()  # clears dupes and number of lines last displayed

      # TODO: Replace this with a shell hook?  with 'trap', or it could be just
      # like command_not_found.  The hook can be 'echo $?' or something more
      # complicated, i.e. with timetamps.
      if flag.print_status:
        print('STATUS', repr(status))

    return status


def Batch(cmd_ev, c_parser, arena, cmd_flags=0):
  # type: (CommandEvaluator, CommandParser, Arena, int) -> int
  """Loop for batch execution.

  Returns:
    int status, e.g. 2 on parse error

  Can this be combined with interative loop?  Differences:
  
  - Handling of parse errors.
  - Have to detect here docs at the end?

  Not a problem:
  - Get rid of --print-status and --show-ast for now
  - Get rid of EOF difference

  TODO:
  - Do source / eval need this?
    - 'source' needs to parse incrementally so that aliases are respected
    - I doubt 'eval' does!  You can test it.
  - In contrast, 'trap' should parse up front?
  - What about $() ?
  """
  status = 0
  while True:
    try:
      node = c_parser.ParseLogicalLine()  # can raise ParseError
      if node is None:  # EOF
        c_parser.CheckForPendingHereDocs()  # can raise ParseError
        break
    except error.Parse as e:
      ui.PrettyPrintError(e, arena)
      status = 2
      break

    # Only optimize if we're on the last line like -c "echo hi" etc.
    if (cmd_flags & cmd_eval.IsMainProgram and
        c_parser.line_reader.LastLineHint()):
      cmd_flags |= cmd_eval.Optimize

    # can't optimize this because we haven't seen the end yet
    is_return, is_fatal = cmd_ev.ExecuteAndCatch(node, cmd_flags=cmd_flags)
    status = cmd_ev.LastStatus()
    # e.g. 'return' in middle of script, or divide by zero
    if is_return or is_fatal:
      break

  return status


def ParseWholeFile(c_parser):
  # type: (CommandParser) -> command_t
  """Parse an entire shell script.

  This uses the same logic as Batch().  Used by:
  - osh -n
  - oshc translate
  - Used by 'trap' to store code.  But 'source' and 'eval' use Batch().
  """
  children = []  # type: List[command_t]
  while True:
    node = c_parser.ParseLogicalLine()  # can raise ParseError
    if node is None:  # EOF
      c_parser.CheckForPendingHereDocs()  # can raise ParseError
      break
    children.append(node)

  if len(children) == 1:
    return children[0]
  else:
    return command.CommandList(children)
