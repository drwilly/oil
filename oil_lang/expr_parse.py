#!/usr/bin/python
"""
expr_parse.py
"""
from __future__ import print_function

import sys

from _devbuild.gen import syntax_asdl
from _devbuild.gen.id_kind_asdl import Id
from _devbuild.gen.types_asdl import lex_mode_e

from core import meta
from core.util import log
from oil_lang import expr_to_ast
from pgen2 import parse


class ParseTreePrinter(object):
  """Prints a tree of PNode instances."""
  def __init__(self, names):
    self.names = names

  def Print(self, pnode, f=sys.stdout, indent=0, i=0):
    ind = '  ' * indent
    # NOTE:
    # - value is filled in for TOKENS, but it's always None for PRODUCTIONS.
    # - context is (prefix, (lineno, column)), where lineno is 1-based, and
    #   'prefix' is a string of whitespace.
    #   e.g. for 'f(1, 3)', the "3" token has a prefix of ' '.
    if isinstance(pnode.tok, tuple):
      v = pnode.tok[0]
    elif isinstance(pnode.tok, syntax_asdl.token):
      v = pnode.tok.val
    else:
      v = '-'
    f.write('%s%d %s %s\n' % (ind, i, self.names[pnode.typ], v))
    if pnode.children:  # could be None
      for i, child in enumerate(pnode.children):
        self.Print(child, indent=indent+1, i=i)


def _Classify(gr, tok):
  # We have to match up what ParserGenerator.make_grammar() did when
  # calling make_label() and make_first().  See classify() in
  # opy/pgen2/driver.py.

  # 'x' and 'for' are both tokenized as Expr_Name.  This handles the 'for'
  # case.
  if tok.id == Id.Expr_Name:
    ilabel = gr.keywords.get(tok.val)
    if ilabel is not None:
      return ilabel

  # This handles 'x'.
  typ = tok.id.enum_id
  ilabel = gr.tokens.get(typ)
  if ilabel is not None:
    return ilabel

  #log('NAME = %s', tok.id.name)
  # 'Op_RBracket' ->
  # Never needed this?
  #id_ = TERMINALS.get(tok.id.name)
  #if id_ is not None:
  #  return id_.enum_id

  raise AssertionError('%d not a keyword and not in gr.tokens: %s' % (typ, tok))


# NOTE: this model is not NOT expressive enough for:
#
# x = func(x, y='default', z={}) {
#   echo hi
# }

# That can probably be handled with some state machine.  Or maybe:
# https://en.wikipedia.org/wiki/Dyck_language
# When you see "func", start matching () and {}, until you hit a new {.
# It's not a regular expression.
#
# Or even more simply:
#   var x = 1 + 2 
# vs.
#   echo hi = 1

# Other issues:
# - Command and Array could be combined?  The parsing of { is different, not
# the lexing.
# - What about SingleLine mode?  With a % prefix?
#   - Assumes {} means brace sub, and also makes trailing \ unnecessary?
#   - Allows you to align pipes on the left
#   - does it mean that only \n\n is a newline?

POP = lex_mode_e.Undefined

_MODE_TRANSITIONS = {
    # DQ_Oil -> ...
    (lex_mode_e.DQ_Oil, Id.Left_DollarSlash): lex_mode_e.Regex,  # "$/ any + /"
    # TODO: Add a token for $/ 'foo' /i .
    # Long version is RegExp($/ 'foo' /, ICASE|DOTALL) ?  Or maybe Regular()
    (lex_mode_e.Regex, Id.Arith_Slash): POP,

    (lex_mode_e.DQ_Oil, Id.Left_DollarBrace): lex_mode_e.VSub_Oil,  # "${x|html}"
    (lex_mode_e.VSub_Oil, Id.Op_RBrace): POP,
    (lex_mode_e.DQ_Oil, Id.Left_DollarBracket): lex_mode_e.Command,  # "$[echo hi]"
    (lex_mode_e.Command, Id.Op_RBracket): POP,
    (lex_mode_e.DQ_Oil, Id.Left_DollarParen): lex_mode_e.Expr,  # "$(1 + 2)"
    (lex_mode_e.Expr, Id.Op_RParen): POP,

    # Expr -> ...
    (lex_mode_e.Expr, Id.Left_AtBracket): lex_mode_e.Array,  # x + @[1 2]
    (lex_mode_e.Array, Id.Op_RBracket): POP,

    (lex_mode_e.Expr, Id.Left_DollarSlash): lex_mode_e.Regex,  # $/ any + /
    (lex_mode_e.Expr, Id.Left_DollarBrace): lex_mode_e.VSub_Oil,  # ${x|html}
    (lex_mode_e.Expr, Id.Left_DollarBracket): lex_mode_e.Command,  # $[echo hi]
    (lex_mode_e.Expr, Id.Left_DollarParen): lex_mode_e.Expr,  # $(1 + 2)
    (lex_mode_e.Expr, Id.Op_LParen): lex_mode_e.Expr,  # $( f(x) )

    (lex_mode_e.Expr, Id.Left_DoubleQuote): lex_mode_e.DQ_Oil,  # x + "foo"
    (lex_mode_e.DQ_Oil, Id.Right_DoubleQuote): POP,

    # Regex
    (lex_mode_e.Regex, Id.Op_LBracket): lex_mode_e.CharClass,  # $/ 'foo.' [c h] /
    (lex_mode_e.CharClass, Id.Op_RBracket): POP,

    (lex_mode_e.Regex, Id.Left_DoubleQuote): lex_mode_e.DQ_Oil,  # $/ "foo" /
    # POP is done above

    (lex_mode_e.Array, Id.Op_LBracket): lex_mode_e.CharClass,  # @[ a *.[c h] ]
    # POP is done above
}


def PushOilTokens(p, lex, gr):
  """Parse a series of tokens and return the syntax tree."""
  #log('keywords = %s', gr.keywords)
  #log('tokens = %s', gr.tokens)

  mode = lex_mode_e.Expr
  mode_stack = [mode]

  while True:
    tok = lex.Read(mode)
    #log('tok = %s', tok)

    # TODO: Use Kind.Ignored
    if tok.id == Id.Ignored_Space:
      continue

    action = _MODE_TRANSITIONS.get((mode, tok.id))
    if action == POP:
      mode_stack.pop()
      mode = mode_stack[-1]
      log('POPPED to %s', mode)
    elif action:  # it's an Id
      new_mode = action
      mode_stack.append(new_mode)
      mode = new_mode
      log('PUSHED to %s', mode)
    # otherwise leave it alone

    #if tok.id == Id.Expr_Name and tok.val in KEYWORDS:
    #  tok.id = KEYWORDS[tok.val]
    #  log('Replaced with %s', tok.id)

    if tok.id.enum_id >= 256:
      raise AssertionError(str(tok))

    ilabel = _Classify(gr, tok)
    #log('tok = %s, ilabel = %d', tok, ilabel)
    if p.addtoken(tok.id.enum_id, tok, ilabel):
      break

  else:
    # We never broke out -- EOF is too soon (how can this happen???)
    raise parse.ParseError("incomplete input", tok.id.enum_id, tok)


def NoSingletonAction(gr, pnode):
  """Collapse parse tree."""
  # hm this was so easy!  Why do CPython and pgen2 materialize so much then?
  children = pnode.children
  if children is not None and len(children) == 1:
    return children[0]

  return pnode


class ExprParser(object):
  """A wrapper around a pgen2 parser."""

  def __init__(self, lexer, gr, start_symbol='eval_input'):
    self.lexer = lexer
    self.gr = gr
    self.push_parser = parse.Parser(gr, convert=NoSingletonAction)
    # TODO: change start symbol?
    self.push_parser.setup(gr.symbol2number[start_symbol])

  def Parse(self, transform=True, print_parse_tree=False):
    try:
      PushOilTokens(self.push_parser, self.lexer, self.gr)
    except parse.ParseError as e:
      log('Parse Error: %s', e)
      raise

    pnode = self.push_parser.rootnode

    if print_parse_tree:
      # Calculate names for pretty-printing.  TODO: Move this into TOK_DEF?
      names = {}

      for id_name, k in meta.ID_SPEC.id_str2int.items():
        # Hm some are out of range
        #assert k < 256, (k, id_name)

        # HACK: Cut it off at 256 now!  Expr/Arith/Op doesn't go higher than
        # that.  TODO: Change NT_OFFSET?  That might affect C code though.
        # Best to keep everything fed to pgen under 256.  This only affects
        # pretty printing.
        if k < 256:
          names[k] = id_name

      for k, v in self.gr.number2symbol.items():
        # eval_input == 256.  Remove?
        assert k >= 256, (k, v)
        names[k] = v

      printer = ParseTreePrinter(names)  # print raw nodes
      printer.Print(pnode)

    # TODO: Remove transform boolean
    if transform:
      tr = expr_to_ast.Transformer(self.gr)
      ast_node = tr.Transform(pnode)
      return ast_node

    return pnode