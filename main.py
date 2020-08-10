import ast
import json
import re
import copy
from uuid import uuid4
from contextlib import contextmanager
from typing import List, Dict, Set

# Input
EXAMPLE_FILE = 'examples/ex_17_class_stuff.py'
DEBUG = False

# TODO
#  - TODO list

class _JavaUnparser(ast._Unparser):
    """Methods in this class recursively traverse an AST and
    output source code for the abstract syntax; original formatting
    is disregarded."""

    NAME_TRANSLATIONS = {
        'print': 'System.out.println',
        'cmath': 'Math',
        # TODO: Import and use these properly
        'input': 'scanner.nextLine',
        # Hacks for casting
        'float': 'Double.valueOf',
        'int': 'Integer.valueOf',
        'str': 'String.valueOf',
    }

    _lazy_scope_vars_tag = 'LAZY_SCOPE_VARS'
    _move_up_tag = 'MOVE_UP_LINE'
    _type_replacmeent_tag_suffix = 'REPLACE_THIS_TYPE'
    _for_scope_prefix = 'for_'
    _class_scope_prefix = 'class_'
    _function_scope_prefix = 'func_'

    def _in_scope(self, name):
        """
        Check if something is in scope. If so, return its Python type
        """
        for scope in reversed(self.current_scopes):
            if name in self.scopes[scope]:
                return self.scopes[scope][name]
        return None

    def _add_to_scope(self, name, python_type, java_type, target, value=None, assigning_to_class_var=False):
        # TODO: Better scope handling
        if assigning_to_class_var:
            for scope in reversed(self.current_scopes):
                if scope.startswith(self._class_scope_prefix):
                    self._lazy_scope[scope].append((java_type, target, value))
                    self.scopes[scope][name] = python_type
                    return
        if len(self.current_scopes) != 1:
            self._lazy_scope['global'].append((java_type, target, value))
        self.scopes[self.current_scopes[0]][name] = python_type

    def _process_type_hint(self, node):
        if isinstance(node, ast.Name):
            return self._python_to_java_types.get(node.id)
        elif isinstance(node, ast.Subscript):
            return f"{self._python_to_java_types.get(node.value.id)}<{self._process_type_hint(node.slice)}>"
        print('WARNING, CANNOT PROCESS TYPE HINT', node)

    # Custom utility functions will be defined above __init__
    def _get_python_type(self, node):
        if isinstance(node, ast.Constant):
            return type(node.value)
        elif isinstance(node, ast.Name):
            type_from_scope = self._in_scope(node.id)
            if type_from_scope:
                return type_from_scope
        if isinstance(node, ast.BinOp):
            operator = self.binop[node.op.__class__.__name__]
            # If it's a basic math operator...
            if operator in ['+', '-', '*', '/', '%', '**', '//']:
                # Then if the left or a right is a float, it's a float
                left_type = self._get_python_type(node.left)
                if left_type == float:
                    return float
                right_type = self._get_python_type(node.right)
                if right_type == float:
                    return float
                # If either are ints and we're doing division, it's float also
                if operator == '/' and int in [left_type, right_type]:
                    return float
                # Otherwise, let's assume the type is the type of the left
                return left_type
        return object

    # TODO: Going to need additional context to handle float vs double, etc...
    _python_to_java_types = {
        float: 'double',
        str: 'String',
        int: 'int',
        bool: 'boolean',
        list: 'List',
        List: 'List',
        'List': 'List',
        set: 'Set',
        Set: 'Set',
        'Set': 'Set',
        dict: 'Map',
        Dict: 'Map',
        'Dict': 'Map'
    }
    # Also support string versions for type hints
    _python_to_java_types.update({key.__name__: value for key, value in
                                  _python_to_java_types.items() if not isinstance(key, str) and hasattr(key, '__name__')})
    _java_to_python_types = {value: key for key, value in _python_to_java_types.items()}

    def _get_java_type(self, node, python_type=None):
        if isinstance(node, ast.Constant):
            # Must check booleans before ints
            if isinstance(node.value, bool):
                return 'boolean'
            if isinstance(node.value, int):
                if 2147483647 >= node.value >= -2147483648:
                    return 'int'
                else:
                    return 'long'
        if python_type is None:
            python_type = self._get_python_type(node)
        return self._python_to_java_types.get(python_type, 'Object')

    def _write_above(self, text):
        self.write(f"<{self._move_up_tag}>{text}</{self._move_up_tag}>")

    def _traverse_for_above(self, node):
        with self.delimit(f"<{self._move_up_tag}>", f"</{self._move_up_tag}>"):
            self.traverse(node)

    def _post_process(self, source):
        # Move up all the lines that need moving up
        source = re.sub(rf'[\n](.*?)<{self._move_up_tag}>(.*)</{self._move_up_tag}>', r'\2\n\1', '\n' + source)
        # TODO: Probably a bad hackfix for overlap. May not work in all situations...
        source = re.sub(rf'</{self._move_up_tag}><{self._move_up_tag}>', '\n', source)
        source = source.strip()

        # Update function return types and such
        for replacement_tag, replacement in self._type_replacements.items():
            source = source.replace(replacement_tag, replacement)

        # Lazy scope
        for scope in self.scopes:
            lazy_scope_tag = f"<{self._lazy_scope_vars_tag}>{scope}</{self._lazy_scope_vars_tag}>"
            lazy_scope = []
            for java_type, node, value in self._lazy_scope.get(scope, []):
                if isinstance(node, str):
                    target_str = node
                elif isinstance(node, ast.Name):
                    target_str = node.id
                elif isinstance(node, ast.Attribute):
                    target_str = node.attr
                else:
                    target_str = 'UNSUPPORTED'
                lazy_scope.append(f"{java_type} {target_str}")
                if value:
                    lazy_scope[-1] += f" = {value}"
                lazy_scope[-1] += ';'
            # Deduplicae and preserve order
            lazy_scope = list(sorted(set(lazy_scope), key=lambda x: lazy_scope.index(x)))
            whitespace = re.search(rf'([^\S\r\n]*){lazy_scope_tag}', source) or ''
            if whitespace != '':
                whitespace = ' ' * (whitespace.regs[-1][1] - whitespace.regs[-1][0])
            lazy_scope = f'\n{whitespace}'.join(lazy_scope)
            # source = re.sub(rf'([^\S\r\n]*){lazy_scope_tag}', lazy_scope, source)
            source = re.sub(rf'{lazy_scope_tag}', lazy_scope, source)
        return source


    def __init__(self):
        # self._source = []
        # self._buffer = []
        # self._precedences = {}
        # self._type_ignores = {}
        # self._indent = 0
        super().__init__()
        self._assignment_type_context = None
        self.scopes = {
            'global': dict()
        }
        self._loops_broken = 0
        self._loop_break_vars_by_scope = {}
        self._lazy_scope = {
            'global': []
        }
        self.current_scopes = ['global']
        # Maps a string to be replaced later with the type to replace it with
        self._type_replacements = {}
        self._current_class = None
        self._current_function = None

    # def interleave(self, inter, f, seq):
    #     """Call f on each item in seq, calling inter() in between."""
    #     seq = iter(seq)
    #     try:
    #         f(next(seq))
    #     except StopIteration:
    #         pass
    #     else:
    #         for x in seq:
    #             inter()
    #             f(x)
    #
    # def items_view(self, traverser, items):
    #     """Traverse and separate the given *items* with a comma and append it to
    #     the buffer. If *items* is a single item sequence, a trailing comma
    #     will be added."""
    #     if len(items) == 1:
    #         traverser(items[0])
    #         self.write(",")
    #     else:
    #         self.interleave(lambda: self.write(", "), traverser, items)
    #
    # def maybe_newline(self):
    #     """Adds a newline if it isn't the start of generated source"""
    #     if self._source:
    #         self.write("\n")
    #
    # def fill(self, text=""):
    #     """Indent a piece of text and append it, according to the current
    #     indentation level"""
    #     self.maybe_newline()
    #     self.write("    " * self._indent + text)
    #
    def write(self, text):
        """Append a piece of text"""
        if DEBUG:
            print(f"`{text}`")
        self._source.append(text)
    #
    # def buffer_writer(self, text):
    #     self._buffer.append(text)
    #
    # @property
    # def buffer(self):
    #     value = "".join(self._buffer)
    #     self._buffer.clear()
    #     return value
    #
    @contextmanager
    def block(self, *, extra=None, begins_scope=True, ends_scope=True):
        """A context manager for preparing the source for blocks. It adds
        the character':', increases the indentation on enter and decreases
        the indentation on exit. If *extra* is given, it will be directly
        appended after the colon character.
        """
        if begins_scope:
            self._begin_scope()
        self.write("{")
        if extra:
            self.write(extra)
        self._indent += 1
        yield
        self._indent -= 1
        self.fill("}")
        if ends_scope:
            self.current_scopes.pop()

    def _begin_scope(self, prefix=None):
        self.current_scopes.append((prefix if prefix else '') + uuid4().hex)
        self._lazy_scope[self.current_scopes[-1]] = []
        self.scopes[self.current_scopes[-1]] = {}

    #
    # @contextmanager
    # def delimit(self, start, end):
    #     """A context manager for preparing the source for expressions. It adds
    #     *start* to the buffer and enters, after exit it adds *end*."""
    #
    #     self.write(start)
    #     yield
    #     self.write(end)
    #
    # def delimit_if(self, start, end, condition):
    #     if condition:
    #         return self.delimit(start, end)
    #     else:
    #         return nullcontext()
    #
    # def require_parens(self, precedence, node):
    #     """Shortcut to adding precedence related parens"""
    #     return self.delimit_if("(", ")", self.get_precedence(node) > precedence)
    #
    # def get_precedence(self, node):
    #     return self._precedences.get(node, _Precedence.TEST)
    #
    # def set_precedence(self, precedence, *nodes):
    #     for node in nodes:
    #         self._precedences[node] = precedence
    #
    # def get_raw_docstring(self, node):
    #     """If a docstring node is found in the body of the *node* parameter,
    #     return that docstring node, None otherwise.
    #
    #     Logic mirrored from ``_PyAST_GetDocString``."""
    #     if not isinstance(
    #             node, (AsyncFunctionDef, FunctionDef, ClassDef, Module)
    #     ) or len(node.body) < 1:
    #         return None
    #     node = node.body[0]
    #     if not isinstance(node, Expr):
    #         return None
    #     node = node.value
    #     if isinstance(node, Constant) and isinstance(node.value, str):
    #         return node
    #
    # def get_type_comment(self, node):
    #     comment = self._type_ignores.get(node.lineno) or node.type_comment
    #     if comment is not None:
    #         return f" # type: {comment}"
    #
    def traverse(self, node):
        if DEBUG:
            print(node.__class__.__name__)
        if isinstance(node, list):
            for item in node:
                self.traverse(item)
        else:
            ast.NodeVisitor.visit(self, node)

    def visit(self, node):
        """Outputs a source code string that, if converted back to an ast
        (using ast.parse) will generate an AST equivalent to *node*"""
        self._source = []
        self.traverse(node)
        return self._post_process("".join(self._source))

    #
    # def _write_docstring_and_traverse_body(self, node):
    #     if (docstring := self.get_raw_docstring(node)):
    #         self._write_docstring(docstring)
    #         self.traverse(node.body[1:])
    #     else:
    #         self.traverse(node.body)
    #
    # def visit_Module(self, node):
    #     self._type_ignores = {
    #         ignore.lineno: f"ignore{ignore.tag}"
    #         for ignore in node.type_ignores
    #     }
    #     self._write_docstring_and_traverse_body(node)
    #     self._type_ignores.clear()
    #
    # def visit_FunctionType(self, node):
    #     with self.delimit("(", ")"):
    #         self.interleave(
    #             lambda: self.write(", "), self.traverse, node.argtypes
    #         )
    #
    #     self.write(" -> ")
    #     self.traverse(node.returns)
    #
    def visit_Expr(self, node):
        #   self.fill()
        #   self.set_precedence(ast._Precedence.YIELD, node.value)
        #   self.traverse(node.value)
        super().visit_Expr(node)
        self.write(';')

    #
    # def visit_NamedExpr(self, node):
    #     with self.require_parens(_Precedence.TUPLE, node):
    #         self.set_precedence(_Precedence.ATOM, node.target, node.value)
    #         self.traverse(node.target)
    #         self.write(" := ")
    #         self.traverse(node.value)
    #
    def visit_Import(self, node):
        # TODO: Imports
        ...
        # node.names[:] = [name_obj for name_obj in node.names if name_obj.name not in self._ignored_imports]
        # if not node.names:
        #     return
        # self.fill("import ")
        # self.interleave(lambda: self.write(", "), self.traverse, node.names)
    #
    def visit_ImportFrom(self, node):
        # TODO: Imports (From)
        ...
        # self.fill("from ")
        # self.write("." * node.level)
        # if node.module:
        #     self.write(node.module)
        # self.write(" import ")
        # self.interleave(lambda: self.write(", "), self.traverse, node.names)
    #
    def visit_Assign(self, node):
        self.fill()
        for target in node.targets:
            if isinstance(target, ast.Tuple):
                if len(target.elts) == len(node.value.elts):
                    for key, value in zip(target.elts, node.value.elts):
                        fake_assign = copy.deepcopy(node)
                        fake_assign.targets = [key]
                        fake_assign.value = value
                        self.visit_Assign(fake_assign)
                    return
                else:
                    print("Unsupported ATM: Mismatched a, b = x")

            elif isinstance(target, ast.Name):
                # TODO: Variable type changes
                for scope in reversed(self.current_scopes):
                    # TODO: Is this really how scopes work?
                    #  No var needed if it's in a parent scope?
                    if target.id in self.scopes[scope]:
                        break
                else:
                    # TODO: Utilize type comment
                    python_type = self._get_python_type(node.value)
                    java_type = self._get_java_type(node, python_type)
                    self._assignment_type_context = python_type
                    if java_type == 'Object':
                        java_type = 'var'  # TODO: Worry about objects?
                    # TODO: Better scope handling
                    if len(self.current_scopes) == 1:
                        self.write(java_type + ' ')
                    # Are we assigning to the current class?
                    self._add_to_scope(target.id, python_type, java_type, target)
            # TODO: Utilize type comments?
            elif isinstance(target, ast.Attribute) \
                and isinstance(target.value, ast.Name) \
                and self.NAME_TRANSLATIONS.get(target.value.id) == 'this':
                python_type = self._get_python_type(node.value)
                java_type = self._get_java_type(node, python_type)
                self._assignment_type_context = python_type
                # TODO: Better scope handling
                if len(self.current_scopes) == 1:
                    self.write(java_type + ' ')
                self._add_to_scope(target.value.id, python_type, java_type, target, None, True)
            elif isinstance(target, ast.Subscript):
                node.targets = [target.value]
                self.visit_Assign(node)
                return
            self.traverse(target)
            self.write(" = ")
        self.traverse(node.value)
        self.write(';')
        self._assignment_type_context = None
        # TODO: Leverage type comments?
        # if type_comment := self.get_type_comment(node):
        #     self.write(type_comment)
    #
    # def visit_AugAssign(self, node):
    #     self.fill()
    #     self.traverse(node.target)
    #     self.write(" " + self.binop[node.op.__class__.__name__] + "= ")
    #     self.traverse(node.value)
    #
    # def visit_AnnAssign(self, node):
    #     self.fill()
    #     with self.delimit_if("(", ")", not node.simple and isinstance(node.target, Name)):
    #         self.traverse(node.target)
    #     self.write(": ")
    #     self.traverse(node.annotation)
    #     if node.value:
    #         self.write(" = ")
    #         self.traverse(node.value)
    #
    def visit_Return(self, node):
        self.fill("return")
        if node.value:
            self.write(" ")
            self.traverse(node.value)
            for scope in reversed(self.current_scopes):
                if scope.startswith(self._function_scope_prefix):
                    replacement_tag = scope + self._type_replacmeent_tag_suffix
                    self._type_replacements[replacement_tag] = self._get_java_type(node.value)
                    break
        self.write(';')

    def visit_Pass(self, node):
        pass  # Actually do nothing. Java doesn't have pass and typically doesn't need it.
    #
    def visit_Break(self, node):
        for scope in reversed(self.current_scopes):
            if scope.startswith(self._for_scope_prefix):
                if (loop_break_var := self._loop_break_vars_by_scope.get(scope)) is not None:
                    self.fill(f"{loop_break_var} = true;")
                break
        self.fill("break;")
    #
    def visit_Continue(self, node):
        self.fill("continue;")
    #
    # def visit_Delete(self, node):
    #     self.fill("del ")
    #     self.interleave(lambda: self.write(", "), self.traverse, node.targets)
    #
    # def visit_Assert(self, node):
    #     self.fill("assert ")
    #     self.traverse(node.test)
    #     if node.msg:
    #         self.write(", ")
    #         self.traverse(node.msg)
    #
    # def visit_Global(self, node):
    #     self.fill("global ")
    #     self.interleave(lambda: self.write(", "), self.write, node.names)
    #
    # def visit_Nonlocal(self, node):
    #     self.fill("nonlocal ")
    #     self.interleave(lambda: self.write(", "), self.write, node.names)
    #
    # def visit_Await(self, node):
    #     with self.require_parens(_Precedence.AWAIT, node):
    #         self.write("await")
    #         if node.value:
    #             self.write(" ")
    #             self.set_precedence(_Precedence.ATOM, node.value)
    #             self.traverse(node.value)
    #
    # def visit_Yield(self, node):
    #     with self.require_parens(_Precedence.YIELD, node):
    #         self.write("yield")
    #         if node.value:
    #             self.write(" ")
    #             self.set_precedence(_Precedence.ATOM, node.value)
    #             self.traverse(node.value)
    #
    # def visit_YieldFrom(self, node):
    #     with self.require_parens(_Precedence.YIELD, node):
    #         self.write("yield from ")
    #         if not node.value:
    #             raise ValueError("Node can't be used without a value attribute.")
    #         self.set_precedence(_Precedence.ATOM, node.value)
    #         self.traverse(node.value)
    #
    # def visit_Raise(self, node):
    #     self.fill("raise")
    #     if not node.exc:
    #         if node.cause:
    #             raise ValueError(f"Node can't use cause without an exception.")
    #         return
    #     self.write(" ")
    #     self.traverse(node.exc)
    #     if node.cause:
    #         self.write(" from ")
    #         self.traverse(node.cause)
    #
    # def visit_Try(self, node):
    #     self.fill("try")
    #     with self.block():
    #         self.traverse(node.body)
    #     for ex in node.handlers:
    #         self.traverse(ex)
    #     if node.orelse:
    #         self.fill("else")
    #         with self.block():
    #             self.traverse(node.orelse)
    #     if node.finalbody:
    #         self.fill("finally")
    #         with self.block():
    #             self.traverse(node.finalbody)
    #
    # def visit_ExceptHandler(self, node):
    #     self.fill("except")
    #     if node.type:
    #         self.write(" ")
    #         self.traverse(node.type)
    #     if node.name:
    #         self.write(" as ")
    #         self.write(node.name)
    #     with self.block():
    #         self.traverse(node.body)
    #
    def visit_ClassDef(self, node):
        self.maybe_newline()
        for deco in node.decorator_list:
            self.fill("@")
            self.traverse(deco)
        self.fill(f"public class {node.name} ")

        # TODO: Subclassing
        # with self.delimit_if("(", ")", condition=node.bases or node.keywords):
        #     comma = False
        #     for e in node.bases:
        #         if comma:
        #             self.write(", ")
        #         else:
        #             comma = True
        #         self.traverse(e)
        #     for e in node.keywords:
        #         if comma:
        #             self.write(", ")
        #         else:
        #             comma = True
        #         self.traverse(e)

        with self.block(begins_scope=False):
            self._begin_scope(prefix=self._class_scope_prefix)
            self.fill(f"<{self._lazy_scope_vars_tag}>{self.current_scopes[-1]}</{self._lazy_scope_vars_tag}>")
            outer_class = self._current_class
            outer_function = self._current_function
            self._current_class = node.name
            self._current_function = None
            self._write_docstring_and_traverse_body(node)
            self._current_class = outer_class
            self._current_function = outer_function

    def visit_FunctionDef(self, node):
        self._function_helper(node, "public")

    def visit_AsyncFunctionDef(self, node):
        self._function_helper(node, "public", is_async=True)

    def _function_helper(self, node, fill_suffix, is_async=False):
        self.maybe_newline()
        # If we're not in a class, we'll treat it as static
        static = not self._current_class
        for deco in node.decorator_list:
            if isinstance(deco, ast.Name) and deco.id == 'staticmethod':
                static = True
                continue
            self.fill("@")
            self.traverse(deco)
        # TODO: Handle async
        scope = 'public'
        self.fill(scope)
        is_constructor = node.name == '__init__' and self._current_class
        if is_constructor:
            node.name = self._current_class
        with self.delimit(f"{' static' if static else ''} ", node.name):
            # Starting the scope a little early to build replacement tag. If this bites me later,
            #   then I might need to use something else besides scope for that tag
            self._begin_scope(prefix=self._function_scope_prefix)
            if not is_constructor:
                # If they gave us a type hint, try to use it
                type_hint = None
                if node.returns:
                    type_hint = self._process_type_hint(node.returns)
                if type_hint:
                    self.write(type_hint)
                else:
                    # TODO: Figure out function return type
                    replacement_tag = self.current_scopes[-1] + self._type_replacmeent_tag_suffix
                    self.write(replacement_tag)
                    self._type_replacements[replacement_tag] = 'void'
                self.write(' ')
        with self.delimit("(", ") "):
            if not static:
                # TODO: Make sure this doesn't mess up things in other contexts
                this_var = node.args.args[0]
                self.NAME_TRANSLATIONS[this_var.arg] = 'this'
                node.args.args[:] = node.args.args[1:]
            self.traverse(node.args)
        with self.block(extra=self.get_type_comment(node), begins_scope=False):
            self.fill(f"<{self._lazy_scope_vars_tag}>{self.current_scopes[-1]}</{self._lazy_scope_vars_tag}>")
            outer_function = self._current_function
            outer_class = self._current_class
            self._current_class = None
            self._current_function = node.name
            self._write_docstring_and_traverse_body(node)
            self._current_function = outer_function
            self._current_class = outer_class
    #
    # def visit_For(self, node):
    #     self._for_helper("for ", node)
    #
    # def visit_AsyncFor(self, node):
    #     self._for_helper("async for ", node)
    #
    def _for_helper(self, fill, node):
        target = node.target
        self.fill(f"<{self._lazy_scope_vars_tag}>{self.current_scopes[-1]}</{self._lazy_scope_vars_tag}>")
        self._begin_scope(prefix=self._for_scope_prefix)
        self.fill(fill)
        loop_broke_var = 'loopBroke'
        if node.orelse:
            if self._loops_broken > 0:
                loop_broke_var += str(self._loops_broken)
            self._loop_break_vars_by_scope[self.current_scopes[-1]] = loop_broke_var
            self._loops_broken += 1
        with self.delimit("(", ")"):
            try:
                was_enumerate = False
                if node.iter.func.id == 'enumerate':
                    was_enumerate = True
                    node.iter.func.id = 'range'

                if node.iter.func.id == 'range':
                    # Special case: range
                    if isinstance(node.target, ast.Tuple):
                        target = node.target.elts[0]

                    if not self._in_scope(target.id):
                        self.write('int ')
                    self.traverse(target)

                    start = step = None
                    if len(node.iter.args) == 1:
                        stop = node.iter.args[0]
                    elif len(node.iter.args) == 2:
                        start, stop = node.iter.args
                    else:
                        start, stop, step = node.iter.args

                    # start
                    self.write(' = ')
                    if start is None:
                        self.write("0")
                    else:
                        self.traverse(start)
                    self.write('; ')

                    # stop
                    self.traverse(target)
                    self.write(' != ')  # TODO: <, >, <=, >=?
                    self.traverse(stop)
                    if was_enumerate:
                        # TODO: .length? .length() Blah!
                        self.write('.size()')
                    self.write('; ')

                    # step
                    if step is not None:
                        self.traverse(target)
                        self.write(' += ')
                        self.traverse(step)
                    else:
                        self.traverse(target)
                        self.write('++')

            except AttributeError:
                if isinstance(node.target, ast.Tuple):
                    elts = node.target.elts
                else:
                    elts = [node.target]
                if len(elts) == 1:
                    if not self._in_scope(node.target.id):
                        self.write('var ')
                    self.traverse(node.target)
                    self.write(": ")
                else:
                    self.write("MappyStuff ")
                    self.traverse(node.target)
                    self.write(": ")
                self.traverse(node.iter)
        with self.block(extra=self.get_type_comment(node), begins_scope=False):
            if was_enumerate and isinstance(node.target, ast.Tuple):
                # TODO: Type
                self.fill("var ")
                self.traverse(node.target.elts[1])
                self.write(" = ")
                self.traverse(node.iter.args[0])
                self.write("[i];")

            self.traverse(node.body)
        if node.orelse:
            self.fill(f"if (!{loop_broke_var})")
            with self.block():
                self._add_to_scope(loop_broke_var, bool, 'boolean', loop_broke_var, 'false')
                self.traverse(node.orelse)
    #
    def visit_If(self, node):
        self.fill(f"<{self._lazy_scope_vars_tag}>{self.current_scopes[-1]}</{self._lazy_scope_vars_tag}>")
        # Simple check for `if __name__ == '__main__'`  # TODO: More complex support?
        if isinstance(node.test, ast.Compare) \
                and isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__' \
                and isinstance(node.test.ops[0], ast.Eq) \
                and isinstance(node.test.comparators[0], ast.Constant) and node.test.comparators[0].value == '__main__':
            self.write("public static void main(String[] args)")
            with self.block():
                self.traverse(node.body)
            return

        self.fill("if ")
        with self.delimit("(", ") "):
            self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        # collapse nested ifs into equivalent elifs.
        while node.orelse and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
            self.fill("else if ")
            with self.delimit("(", ") "):
                self.traverse(node.test)
            with self.block():
                self.traverse(node.body)
        # final else
        if node.orelse:
            self.fill("else ")
            with self.block():
                self.traverse(node.orelse)
    #
    # def visit_While(self, node):
    #     self.fill("while ")
    #     self.traverse(node.test)
    #     with self.block():
    #         self.traverse(node.body)
    #     if node.orelse:
    #         self.fill("else")
    #         with self.block():
    #             self.traverse(node.orelse)
    #
    # def visit_With(self, node):
    #     self.fill("with ")
    #     self.interleave(lambda: self.write(", "), self.traverse, node.items)
    #     with self.block(extra=self.get_type_comment(node)):
    #         self.traverse(node.body)
    #
    # def visit_AsyncWith(self, node):
    #     self.fill("async with ")
    #     self.interleave(lambda: self.write(", "), self.traverse, node.items)
    #     with self.block(extra=self.get_type_comment(node)):
    #         self.traverse(node.body)
    #
    # def visit_JoinedStr(self, node):
    #     self.write("f")
    #     self._fstring_JoinedStr(node, self.buffer_writer)
    #     self.write(repr(self.buffer))
    #
    # def visit_FormattedValue(self, node):
    #     self.write("f")
    #     self._fstring_FormattedValue(node, self.buffer_writer)
    #     self.write(repr(self.buffer))
    #
    # def _fstring_JoinedStr(self, node, write):
    #     for value in node.values:
    #         meth = getattr(self, "_fstring_" + type(value).__name__)
    #         meth(value, write)
    #
    # def _fstring_Constant(self, node, write):
    #     if not isinstance(node.value, str):
    #         raise ValueError("Constants inside JoinedStr should be a string.")
    #     value = node.value.replace("{", "{{").replace("}", "}}")
    #     write(value)
    #
    # def _fstring_FormattedValue(self, node, write):
    #     write("{")
    #     unparser = type(self)()
    #     unparser.set_precedence(_Precedence.TEST.next(), node.value)
    #     expr = unparser.visit(node.value)
    #     if expr.startswith("{"):
    #         write(" ")  # Separate pair of opening brackets as "{ {"
    #     write(expr)
    #     if node.conversion != -1:
    #         conversion = chr(node.conversion)
    #         if conversion not in "sra":
    #             raise ValueError("Unknown f-string conversion.")
    #         write(f"!{conversion}")
    #     if node.format_spec:
    #         write(":")
    #         meth = getattr(self, "_fstring_" + type(node.format_spec).__name__)
    #         meth(node.format_spec, write)
    #     write("}")
    #
    def visit_Name(self, node):
        self.write(self.NAME_TRANSLATIONS.get(node.id, node.id))

    def _write_docstring(self, node):
        def esc_char(c):
            if c in ("\n", "\t"):
                # In the AST form, we don't know the author's intentation
                # about how this should be displayed. We'll only escape
                # \n and \t, because they are more likely to be unescaped
                # in the source
                return c
            return c.encode('unicode_escape').decode('ascii')

        self.fill()
        if node.kind == "u":
            self.write("u")

        value = node.value
        if value:
            # Preserve quotes in the docstring by escaping them
            value = "".join(map(esc_char, value))
            if value[-1] == '"':
                value = value.replace('"', '\\"', -1)
            value = value.replace('*/', '*\\/')

        self.write(f'/**{value}*/')

    def _write_constant(self, value):
        if isinstance(value, (float, complex)):
            # Substitute overflowing decimal literal for AST infinities.
            self.write(repr(value).replace("inf", ast._INFSTR))
        elif isinstance(value, str):
            # TODO: Better formatting for Java strings.
            self.write(json.dumps(value))
        else:
            self.write(repr(value))
    #
    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, tuple):
            with self.delimit("(", ")"):
                self.items_view(self._write_constant, value)
        elif isinstance(value, bool):
            self.write(str(value).lower())
        elif value is ...:
            self.write("...")
        else:
            if node.kind == "u":
                self.write("u")
            self._write_constant(node.value)
    #
    # def visit_List(self, node):
    #     with self.delimit("[", "]"):
    #         self.interleave(lambda: self.write(", "), self.traverse, node.elts)
    #
    # def visit_ListComp(self, node):
    #     with self.delimit("[", "]"):
    #         self.traverse(node.elt)
    #         for gen in node.generators:
    #             self.traverse(gen)
    #
    # def visit_GeneratorExp(self, node):
    #     with self.delimit("(", ")"):
    #         self.traverse(node.elt)
    #         for gen in node.generators:
    #             self.traverse(gen)
    #
    # def visit_SetComp(self, node):
    #     with self.delimit("{", "}"):
    #         self.traverse(node.elt)
    #         for gen in node.generators:
    #             self.traverse(gen)
    #
    # def visit_DictComp(self, node):
    #     with self.delimit("{", "}"):
    #         self.traverse(node.key)
    #         self.write(": ")
    #         self.traverse(node.value)
    #         for gen in node.generators:
    #             self.traverse(gen)
    #
    # def visit_comprehension(self, node):
    #     if node.is_async:
    #         self.write(" async for ")
    #     else:
    #         self.write(" for ")
    #     self.set_precedence(_Precedence.TUPLE, node.target)
    #     self.traverse(node.target)
    #     self.write(" in ")
    #     self.set_precedence(_Precedence.TEST.next(), node.iter, *node.ifs)
    #     self.traverse(node.iter)
    #     for if_clause in node.ifs:
    #         self.write(" if ")
    #         self.traverse(if_clause)
    #
    # def visit_IfExp(self, node):
    #     with self.require_parens(_Precedence.TEST, node):
    #         self.set_precedence(_Precedence.TEST.next(), node.body, node.test)
    #         self.traverse(node.body)
    #         self.write(" if ")
    #         self.traverse(node.test)
    #         self.write(" else ")
    #         self.set_precedence(_Precedence.TEST, node.orelse)
    #         self.traverse(node.orelse)
    #
    # def visit_Set(self, node):
    #     if not node.elts:
    #         raise ValueError("Set node should have at least one item")
    #     with self.delimit("{", "}"):
    #         self.interleave(lambda: self.write(", "), self.traverse, node.elts)
    #
    # def visit_Dict(self, node):
    #     def write_key_value_pair(k, v):
    #         self.traverse(k)
    #         self.write(": ")
    #         self.traverse(v)
    #
    #     def write_item(item):
    #         k, v = item
    #         if k is None:
    #             # for dictionary unpacking operator in dicts {**{'y': 2}}
    #             # see PEP 448 for details
    #             self.write("**")
    #             self.set_precedence(_Precedence.EXPR, v)
    #             self.traverse(v)
    #         else:
    #             write_key_value_pair(k, v)
    #
    #     with self.delimit("{", "}"):
    #         self.interleave(
    #             lambda: self.write(", "), write_item, zip(node.keys, node.values)
    #         )
    #
    # def visit_Tuple(self, node):
    #     with self.delimit("(", ")"):
    #         self.items_view(self.traverse, node.elts)
    #
    # unop = {"Invert": "~", "Not": "not", "UAdd": "+", "USub": "-"}
    # unop_precedence = {
    #     "not": _Precedence.NOT,
    #     "~": _Precedence.FACTOR,
    #     "+": _Precedence.FACTOR,
    #     "-": _Precedence.FACTOR,
    # }
    #
    # def visit_UnaryOp(self, node):
    #     operator = self.unop[node.op.__class__.__name__]
    #     operator_precedence = self.unop_precedence[operator]
    #     with self.require_parens(operator_precedence, node):
    #         self.write(operator)
    #         # factor prefixes (+, -, ~) shouldn't be seperated
    #         # from the value they belong, (e.g: +1 instead of + 1)
    #         if operator_precedence is not _Precedence.FACTOR:
    #             self.write(" ")
    #         self.set_precedence(operator_precedence, node.operand)
    #         self.traverse(node.operand)
    #
    # binop = {
    #     "Add": "+",
    #     "Sub": "-",
    #     "Mult": "*",
    #     "MatMult": "@",
    #     "Div": "/",
    #     "Mod": "%",
    #     "LShift": "<<",
    #     "RShift": ">>",
    #     "BitOr": "|",
    #     "BitXor": "^",
    #     "BitAnd": "&",
    #     "FloorDiv": "//",
    #     "Pow": "**",
    # }
    #
    # binop_precedence = {
    #     "+": _Precedence.ARITH,
    #     "-": _Precedence.ARITH,
    #     "*": _Precedence.TERM,
    #     "@": _Precedence.TERM,
    #     "/": _Precedence.TERM,
    #     "%": _Precedence.TERM,
    #     "<<": _Precedence.SHIFT,
    #     ">>": _Precedence.SHIFT,
    #     "|": _Precedence.BOR,
    #     "^": _Precedence.BXOR,
    #     "&": _Precedence.BAND,
    #     "//": _Precedence.TERM,
    #     "**": _Precedence.POWER,
    # }
    #
    # binop_rassoc = frozenset(("**",))
    #
    def visit_BinOp(self, node):
        operator = self.binop[node.op.__class__.__name__]
        operator_precedence = self.binop_precedence[operator]
        with self.require_parens(operator_precedence, node):
            if operator in self.binop_rassoc:
                left_precedence = operator_precedence.next()
                right_precedence = operator_precedence
            else:
                left_precedence = operator_precedence
                right_precedence = operator_precedence.next()

            self.set_precedence(left_precedence, node.left)
            if operator == '**':  # Java doesn't have **
                # Special case: Exponents
                # If the assignment context is int, but we're using Math.pow
                #  which returns a double, then cast to an int
                # TODO: Not always necessary depending on the entire operation...
                #  the goal of this project is to have as little "unnecessary" stuff
                #  as possible, so this should be fixed.
                if self._assignment_type_context == int:
                    self.write("(int) ")

                self.write('Math.pow(')
                self.traverse(node.left)
                self.write(', ')
                self.set_precedence(right_precedence, node.right)
                self.traverse(node.right)
                self.write(')')
            elif operator == '%' and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                # Special case: Modulus on a string
                self.write('String.format(')
                # https://www.javatpoint.com/java-string-format
                format_specifiers = 'abcdefghostx'
                format_float_specifiers = 'aefg'
                # Java wants %.3f not %0.3f, etc
                node.left.value = re.sub(rf'%0.(\d+)([{format_specifiers}])', r'%.\1\2', node.left.value)

                # Figure out type casts we might need to make if the values don't match up already
                possible_type_casts = []
                for format_specifier in re.findall(rf'%.?\d*([{format_specifiers}])', node.left.value):
                    if format_specifier in format_float_specifiers:
                        possible_type_casts.append(float)
                    else:
                        possible_type_casts.append(None)

                self.traverse(node.left)
                self.write(', ')
                self.set_precedence(right_precedence, node.right)
                if isinstance(node.right, ast.Tuple):
                    for possible_type_cast, item in zip(possible_type_casts[:-1], node.right.elts[:-1]):
                        python_type = self._get_python_type(item)
                        if possible_type_cast and not python_type == possible_type_cast:
                            self.write(f"({self._python_to_java_types[possible_type_cast]}) ")
                        self.traverse(item)
                        self.write(', ')
                    if possible_type_casts[-1] and not self._get_python_type(node.right.elts[-1]) == possible_type_casts[-1]:
                        self.write(f"({self._python_to_java_types[possible_type_casts[-1]]}) ")
                    self.traverse(node.right.elts[-1])
                else:
                    if possible_type_casts[0] and not self._get_python_type(node.right) == possible_type_casts[0]:
                        self.write(f"({self._python_to_java_types[possible_type_casts[0]]}) ")
                    self.traverse(node.right)
                self.write(')')
            elif operator == '/' or operator == '//':
                if operator == '//':
                    delimiters = 'Math.floor(', ')'
                else:
                    delimiters = '', ''
                operator = '/'
                with self.delimit(*delimiters):
                    # Handle floating point
                    left_type = self._get_python_type(node.left)
                    # right_type = self._get_python_type(node.right)
                    if self._assignment_type_context and self._assignment_type_context != left_type:
                        self.write(f"({self._python_to_java_types[self._assignment_type_context]}) " )
                    self.traverse(node.left)
                    self.write(f" {operator} ")
                    # Unnecessary?
                    # if self._assignment_type_context != right_type:
                    #     self.write(f"({self._python_to_java_types[self._assignment_type_context]}) ")
                    self.set_precedence(right_precedence, node.right)
                    self.traverse(node.right)
            else:
                self.traverse(node.left)
                self.write(f" {operator} ")
                self.set_precedence(right_precedence, node.right)
                self.traverse(node.right)
    #
    # cmpops = {
    #     "Eq": "==",
    #     "NotEq": "!=",
    #     "Lt": "<",
    #     "LtE": "<=",
    #     "Gt": ">",
    #     "GtE": ">=",
    #     "Is": "is",
    #     "IsNot": "is not",
    #     "In": "in",
    #     "NotIn": "not in",
    # }
    #
    # def visit_Compare(self, node):
    #     with self.require_parens(_Precedence.CMP, node):
    #         self.set_precedence(_Precedence.CMP.next(), node.left, *node.comparators)
    #         self.traverse(node.left)
    #         for o, e in zip(node.ops, node.comparators):
    #             self.write(" " + self.cmpops[o.__class__.__name__] + " ")
    #             self.traverse(e)
    #
    boolops = {"And": "&&", "Or": "||"}
    boolop_precedence = {"&&": ast._Precedence.AND, "||": ast._Precedence.OR}
    #
    # def visit_BoolOp(self, node):
    #     operator = self.boolops[node.op.__class__.__name__]
    #     operator_precedence = self.boolop_precedence[operator]
    #
    #     def increasing_level_traverse(node):
    #         nonlocal operator_precedence
    #         operator_precedence = operator_precedence.next()
    #         self.set_precedence(operator_precedence, node)
    #         self.traverse(node)
    #
    #     with self.require_parens(operator_precedence, node):
    #         s = f" {operator} "
    #         self.interleave(lambda: self.write(s), increasing_level_traverse, node.values)
    #
    def visit_Attribute(self, node):
        self.set_precedence(ast._Precedence.ATOM, node.value)
        self.traverse(node.value)
        # Special case: 3.__abs__() is a syntax error, so if node.value
        # is an integer literal then we need to either parenthesize
        # it or add an extra space to get 3 .__abs__().
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
            self.write(" ")
        self.write(".")

        # Special cases
        if isinstance(node.value, ast.Name):
            # Special case: random
            if node.value.id == 'random':
                # TODO: What if random is in scope but isn't actually a random?
                if not self._in_scope('random'):
                    with self.delimit(f"<{self._move_up_tag}>", f"</{self._move_up_tag}>"):
                        self.write('java.util.Random random = new java.util.Random();')
                    self._add_to_scope('random', 'random', 'random', 'java.util.Random')  # TODO: Adding non-python type, smelly
                if node.attr == 'randint':
                    self.write('nextInt')
                    return

        self.write(node.attr)
    #
    def visit_Call(self, node):
        self.set_precedence(ast._Precedence.ATOM, node.func)
        delimiter_1, delimiter_2 = "(", ")"

        if isinstance(node.func, ast.Attribute) and node.func.attr == 'randint' and len(node.args) == 2:
            # Special case: randint # TODO: Check to verify random is being called?
            minimum, maximum = node.args
            if isinstance(maximum, ast.Constant) and isinstance(minimum, ast.Constant):
                bound = node.args[1].value - node.args[0].value
                if minimum.value != 0:
                    self.write(f"{minimum.value} + ")
                self.traverse(node.func)
                with self.delimit(delimiter_1, delimiter_2):
                    self.write(str(bound))
            else:
                self.traverse(minimum)
                self.write(' + ')
                self.traverse(node.func)
                with self.delimit(delimiter_1, delimiter_2):
                    self.traverse(maximum)
                    if not (isinstance(minimum, ast.Constant) and minimum.value == 0):
                        self.write(" - ")
                        self.traverse(minimum)
            return

        if isinstance(node.func, ast.Name):
            if node.func.id == 'input':
                # Special case: input
                # TODO: What if scanner is in scope but isn't actually a scanner?
                if not self._in_scope('scanner'):
                    with self.delimit(f"<{self._move_up_tag}>", f"</{self._move_up_tag}>"):
                        self.write('java.util.Scanner scanner = new java.util.Scanner(System.in);')
                    self._add_to_scope('scanner', 'scanner', 'scanner', 'java.util.Scanner')  # TODO: Adding non-python type, smelly

                with self.delimit(f"<{self._move_up_tag}>", f"</{self._move_up_tag}>"):
                    self.write("System.out.print")

                    with self.delimit(delimiter_1, delimiter_2):
                        comma = False
                        for e in node.args:
                            if comma:
                                self.write(", ")
                            else:
                                comma = True
                            self.traverse(e)
                        for e in node.keywords:
                            if comma:
                                self.write(", ")
                            else:
                                comma = True
                            self.traverse(e)
                    self.write(';')
                self.traverse(node.func)
                self.write("()")
                return

            if node.func.id == 'print' and len(node.args) > 1:
                # Special case: print
                # TODO: Handle keywords
                self.traverse(node.func)
                with self.delimit(delimiter_1, delimiter_2):
                    plus = False
                    for e in node.args:
                        if plus:
                            self.write(' + " " + ')
                        else:
                            plus = True
                        self.traverse(e)
                return


        # Special case: "somestring".format
        if isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'format' \
                and isinstance(node.func.value, ast.Constant) \
                and isinstance(node.func.value.value, str):
            self.write("String.format(")
            # TODO: Optimize
            # {0} -> %\1$s
            string = node.func.value.value
            match = re.search('{(\d+)}', string)
            while match:
                start, end = match.start(), match.end()
                string = f"{string[:start+1]}{int(string[start+1:end-1])+1}{string[end-1:]}"
                match = re.search('{(\d+)}', ' ' * end + string[end:])
            # {} -> %s
            string = string.replace('{}', '%s')
            node.func.value.value = re.sub('{(\d+)}', r'%\1$s', string)
            self.traverse(node.func.value)
            self.write(", ")
            delimiter_1 = ""  # Skip open parentheses
        else:
            # All other cases
            self.traverse(node.func)

        with self.delimit(delimiter_1, delimiter_2):
            comma = False
            for e in node.args:
                if comma:
                    self.write(", ")
                else:
                    comma = True
                self.traverse(e)
            for e in node.keywords:
                if comma:
                    self.write(", ")
                else:
                    comma = True
                self.traverse(e)
    #
    # def visit_Subscript(self, node):
    #     def is_simple_tuple(slice_value):
    #         # when unparsing a non-empty tuple, the parantheses can be safely
    #         # omitted if there aren't any elements that explicitly requires
    #         # parantheses (such as starred expressions).
    #         return (
    #                 isinstance(slice_value, Tuple)
    #                 and slice_value.elts
    #                 and not any(isinstance(elt, Starred) for elt in slice_value.elts)
    #         )
    #
    #     self.set_precedence(_Precedence.ATOM, node.value)
    #     self.traverse(node.value)
    #     with self.delimit("[", "]"):
    #         if is_simple_tuple(node.slice):
    #             self.items_view(self.traverse, node.slice.elts)
    #         else:
    #             self.traverse(node.slice)
    #
    # def visit_Starred(self, node):
    #     self.write("*")
    #     self.set_precedence(_Precedence.EXPR, node.value)
    #     self.traverse(node.value)
    #
    # def visit_Ellipsis(self, node):
    #     self.write("...")
    #
    # def visit_Slice(self, node):
    #     if node.lower:
    #         self.traverse(node.lower)
    #     self.write(":")
    #     if node.upper:
    #         self.traverse(node.upper)
    #     if node.step:
    #         self.write(":")
    #         self.traverse(node.step)
    #
    def visit_arg(self, node):
        type_hint = None
        if node.annotation:
            type_hint = self._process_type_hint(node.annotation)
        if type_hint:
            self.write(type_hint)
            self.scopes[self.current_scopes[-1]][node.arg] = self._java_to_python_types.get(type_hint, 'Object')
        else:
            # TODO: Figure out function return type
            self.write('Object')
            self.scopes[self.current_scopes[-1]][node.arg] = self._java_to_python_types.get('Object', 'Object')
        self.write(' ')
        self.write(node.arg)
    #
    def visit_arguments(self, node):
        first = True
        # normal arguments
        all_args = node.posonlyargs + node.args
        defaults = [None] * (len(all_args) - len(node.defaults)) + node.defaults
        for index, elements in enumerate(zip(all_args, defaults), 1):
            a, d = elements
            if first:
                first = False
            else:
                self.write(", ")
            self.traverse(a)
            if d:
                self.write("=")
                self.traverse(d)
            if index == len(node.posonlyargs):
                self.write(", /")

        # varargs, or bare '*' if no varargs but keyword-only arguments present
        if node.vararg or node.kwonlyargs:
            if first:
                first = False
            else:
                self.write(", ")
            self.write("*")
            if node.vararg:
                self.write(node.vararg.arg)
                if node.vararg.annotation:
                    self.write(": ")
                    self.traverse(node.vararg.annotation)

        # keyword-only arguments
        if node.kwonlyargs:
            for a, d in zip(node.kwonlyargs, node.kw_defaults):
                self.write(", ")
                self.traverse(a)
                if d:
                    self.write("=")
                    self.traverse(d)

        # kwargs
        if node.kwarg:
            if first:
                first = False
            else:
                self.write(", ")
            self.write("**" + node.kwarg.arg)
            if node.kwarg.annotation:
                self.write(": ")
                self.traverse(node.kwarg.annotation)
    #
    # def visit_keyword(self, node):
    #     if node.arg is None:
    #         self.write("**")
    #     else:
    #         self.write(node.arg)
    #         self.write("=")
    #     self.traverse(node.value)
    #
    # def visit_Lambda(self, node):
    #     with self.require_parens(_Precedence.TEST, node):
    #         self.write("lambda ")
    #         self.traverse(node.args)
    #         self.write(": ")
    #         self.set_precedence(_Precedence.TEST, node.body)
    #         self.traverse(node.body)
    #
    # def visit_alias(self, node):
    #     self.write(node.name)
    #     if node.asname:
    #         self.write(" as " + node.asname)
    #
    # def visit_withitem(self, node):
    #     self.traverse(node.context_expr)
    #     if node.optional_vars:
    #         self.write(" as ")
    #         self.traverse(node.optional_vars)


def main():
    with open(EXAMPLE_FILE, 'r') as f:
        tree = ast.parse(f.read())
    result = java_unparse(tree)
    if DEBUG:
        print('====== END DEBUG ======')
    print(result)


def java_unparse(ast_obj):
    unparser = _JavaUnparser()
    return unparser.visit(ast_obj)


if __name__ == '__main__':
    main()
