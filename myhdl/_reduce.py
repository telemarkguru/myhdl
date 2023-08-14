import inspect
import ast
from ._ast import parse_func
from ._intbv import intbv
from ._modbv import modbv


_globals = {"intbv": intbv, "modbv": modbv}


class _Unbound:
    pass


def _cell_contents(cell):
    try:
        return cell.cell_contents
    except ValueError:
        return _Unbound


def _closure_locals(func):
    """Extract function closure constants"""
    if func.__closure__ is None:
        return {}
    try:
        return {
            var: _cell_contents(cell)
            for var, cell in zip(func.__code__.co_freevars, func.__closure__)
        }
    except ValueError:
        unbound = []
        for var, cell in zip(func.__code__.co_freevars, func.__closure__):
            try:
                c = cell.cell_contents
            except ValueError:
                unbound.append(var)
        raise ValueError(
            f"Use of undefined variables: {unbound}. "
            "Maybe declared after function?"
        )


def _is_const(x):
    return isinstance(x, (intbv, int, str, bool)) or x is None


def _closure_constants(clocals):
    return {x: clocals[x] for x in clocals if _is_const(clocals[x])}


def _replace_constant(node, constants):
    """Return Constant if Name node points to variable in constants"""
    if isinstance(node, ast.Name) and node.id in constants:
        return ast.Constant(value=constants[node.id])
    else:
        return node


class _InsertConstants(ast.NodeTransformer):
    """Insert and propagate constants"""

    def _op(self, node):
        self.generic_visit(node)
        node.left = _replace_constant(node.left, self.constants)
        node.right = _replace_constant(node.right, self.constants)
        left_const = isinstance(node.left, ast.Constant)
        right_const = isinstance(node.right, ast.Constant)
        if left_const and right_const:
            value = eval(ast.unparse(node), _globals, self.clocals)
            return ast.Constant(value=value)
        else:
            return node

    def visit_BinOp(self, node):
        return self._op(node)

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        node.values = [
            _replace_constant(x, self.constants) for x in node.values
        ]
        if isinstance(node.op, ast.And):
            values = []
            for x in node.values:
                if isinstance(x, ast.Constant):
                    if not x.value:
                        return ast.Constant(value=False)
                else:
                    values.append(x)
            node.values = values
        else:  # Or:
            values = []
            for x in node.values:
                if isinstance(x, ast.Constant):
                    if x.value:
                        return ast.Constant(value=True)
                else:
                    values.append(x)
            node.values = values
        if all(isinstance(x, ast.Constant) for x in node.values):
            value = eval(ast.unparse(node), _globals, self.clocals)
            return ast.Constant(value=value)
        else:
            return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        node.operand = _replace_constant(node.operand, self.constants)
        if isinstance(node.operand, ast.Constant):
            value = eval(ast.unparse(node), _globals, self.clocals)
            return ast.Constant(value=value)
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        node.left = _replace_constant(node.left, self.constants)
        node.comparators = [
            _replace_constant(x, self.constants) for x in node.comparators
        ]
        if all(
            isinstance(x, ast.Constant)
            for x in ([node.left] + node.comparators)
        ):
            try:
                value = eval(ast.unparse(node), _globals, self.clocals)
                return ast.Constant(value=value)
            except:
                return node
        else:
            return node

    def visit_If(self, node):
        self.generic_visit(node)
        node.test = _replace_constant(node.test, self.constants)
        return node

    # def visit_Attribute(node):
    #     self.generic_visit(node)
    #     value = node.value
    #     if (
    #         isinstance(value, ast.Attribute)
    #         and isinstance(value.ctx, ast.Load)
    #     ):
    #         id = value.id
    #         if id in self.clocals:
    #            pass   -- dunno if there is a case for this....


    # def visit_Call(self, node):
    #     """
    #     If all function call arguments are constants, assume the
    #     result of the function can be evaluated to a constant value.
    #     """
    #     self.generic_visit(node)
    #     node.args = [_replace_constant(x, self.constants) for x in node.args]
    #     node.keywords = {
    #         x: _replace_constant(node.keywords[x], self.constants)
    #         for x in node.keywords
    #     }
    #     if all(
    #         isinstance(x, ast.Constant)
    #         for x in node.args + list(node.keywords.values())
    #     ):
    #         value = eval(ast.unparse(node), {}, self.clocals)
    #         return ast.Constant(value=value)
    #     else:
    #         # func = self.constants[node.func.id]
    #         # funcnode = _inline(func, node.func.id)
    #         # return funcnode or node
    #         return node

    def __init__(self, name, clocals):
        super().__init__()
        self.name = name
        self.constants = _closure_constants(clocals)
        self.clocals = clocals


def _insert_constants(tree, name, constants):
    """Replace Name nodes with constants"""
    return ast.fix_missing_locations(
        _InsertConstants(name, constants).visit(tree)
    )


class _ConstIfRemover(ast.NodeTransformer):
    def visit_If(self, node):
        self.generic_visit(node)
        if isinstance(node.test, ast.Constant):
            if node.test.value:
                return node.body
            else:
                return node.orelse
        else:
            return node


def _remove_const_if(tree):
    return ast.fix_missing_locations(_ConstIfRemover().visit(tree))


class _Inliner(ast.NodeTransformer):

    def __init__(self, local_vars, prefix):
        super().__init__()
        self.local_vars = set(local_vars)
        self.prefix = prefix

    def visit_Name(self, node):
        self.generic_visit(node)
        if node.id in self.local_vars:
            node.id = f"{self.prefix}__{node.id}"
        return node

    def vist_Call(self, node):
        self.generic_visit(node)
        func = getattr(node.name)
        if func and getattr(func, "_inline"):
            return _inline(func, f"{self.prefix}__{node.name}")
        else:
            return node


def _inline(func, prefix):
    """Return AST for inlining of given function"""
    if not hasattr(func, "_inline"):
        return None
    tree = parse_func(func)
    local_vars = func.__code__.co_varnames
    tree = ast.fix_missing_locations(_Inliner(local_vars, prefix).visit(tree))
    body = tree.body[0].body[0].value
    return body


def reduce(func):
    """Return reduced AST of given function"""
    clocals = _closure_locals(func)
    tree = parse_func(func)
    _insert_constants(tree, func.__name__, clocals)
    tree = _remove_const_if(tree)
    return tree


if __name__ == "__main__":

    t1 = ast.parse("if not (1-bar): pass")
    t2 = _insert_constants(t1, "foo", {"bar": 1})
    print(ast.dump(t2, indent="    "))
