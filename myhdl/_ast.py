import inspect
import ast
from tokenize import generate_tokens, untokenize, INDENT
from io import StringIO


def _dedent(s):
    """Dedent python code string."""
    result = [t[:2] for t in generate_tokens(StringIO(s).readline)]
    if result[0][0] == INDENT:
        result[0] = (INDENT, "")
    return untokenize(result)


def parse_func(func):
    """Parse function source and return AST"""
    source = _dedent(inspect.getsource(func))
    tree = compile(
        source,
        mode="exec",
        filename="<unknown>",
        dont_inherit=True,
        flags=ast.PyCF_ONLY_AST,
    )
    # _check_tree(tree)
    return tree


def _check_tree(tree):
    """Check if tree is convertible"""
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if func:
                raise SyntaxError("Nested functions are not allowed")
            func = node
