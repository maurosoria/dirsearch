import railroad
import pyparsing
from pkg_resources import resource_filename
from typing import (
    List,
    Optional,
    NamedTuple,
    Generic,
    TypeVar,
    Dict,
    Callable,
)
from jinja2 import Template
from io import StringIO
import inspect

with open(resource_filename(__name__, "template.jinja2"), encoding="utf-8") as fp:
    template = Template(fp.read())

# Note: ideally this would be a dataclass, but we're supporting Python 3.5+ so we can't do this yet
NamedDiagram = NamedTuple(
    "NamedDiagram",
    [("name", str), ("diagram", Optional[railroad.DiagramItem]), ("index", int)],
)
"""
A simple structure for associating a name with a railroad diagram
"""

T = TypeVar("T")


class EditablePartial(Generic[T]):
    """
    Acts like a functools.partial, but can be edited. In other words, it represents a type that hasn't yet been
    constructed.
    """

    # We need this here because the railroad constructors actually transform the data, so can't be called until the
    # entire tree is assembled

    def __init__(self, func: Callable[..., T], args: list, kwargs: dict):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    @classmethod
    def from_call(cls, func: Callable[..., T], *args, **kwargs) -> "EditablePartial[T]":
        """
        If you call this function in the same way that you would call the constructor, it will store the arguments
        as you expect. For example EditablePartial.from_call(Fraction, 1, 3)() == Fraction(1, 3)
        """
        return EditablePartial(func=func, args=list(args), kwargs=kwargs)

    def __call__(self) -> T:
        """
        Evaluate the partial and return the result
        """
        args = self.args.copy()
        kwargs = self.kwargs.copy()

        # This is a helpful hack to allow you to specify varargs parameters (e.g. *args) as keyword args (e.g.
        # args=['list', 'of', 'things'])
        arg_spec = inspect.getfullargspec(self.func)
        if arg_spec.varargs in self.kwargs:
            args += kwargs.pop(arg_spec.varargs)

        return self.func(*args, **kwargs)


def railroad_to_html(diagrams: List[NamedDiagram], **kwargs) -> str:
    """
    Given a list of NamedDiagram, produce a single HTML string that visualises those diagrams
    :params kwargs: kwargs to be passed in to the template
    """
    data = []
    for diagram in diagrams:
        io = StringIO()
        diagram.diagram.writeSvg(io.write)
        title = diagram.name
        if diagram.index == 0:
            title += " (root)"
        data.append({"title": title, "text": "", "svg": io.getvalue()})

    return template.render(diagrams=data, **kwargs)


def resolve_partial(partial: "EditablePartial[T]") -> T:
    """
    Recursively resolves a collection of Partials into whatever type they are
    """
    if isinstance(partial, EditablePartial):
        partial.args = resolve_partial(partial.args)
        partial.kwargs = resolve_partial(partial.kwargs)
        return partial()
    elif isinstance(partial, list):
        return [resolve_partial(x) for x in partial]
    elif isinstance(partial, dict):
        return {key: resolve_partial(x) for key, x in partial.items()}
    else:
        return partial


def to_railroad(
    element: pyparsing.ParserElement,
    diagram_kwargs: dict = {},
    vertical: int = None,
) -> List[NamedDiagram]:
    """
    Convert a pyparsing element tree into a list of diagrams. This is the recommended entrypoint to diagram
    creation if you want to access the Railroad tree before it is converted to HTML
    :param diagram_kwargs: kwargs to pass to the Diagram() constructor
    :param vertical: (optional)
    """
    # Convert the whole tree underneath the root
    lookup = ConverterState(diagram_kwargs=diagram_kwargs)
    _to_diagram_element(element, lookup=lookup, parent=None, vertical=vertical)

    root_id = id(element)
    # Convert the root if it hasn't been already
    if root_id in lookup.first:
        lookup.first[root_id].mark_for_extraction(root_id, lookup, force=True)

    # Now that we're finished, we can convert from intermediate structures into Railroad elements
    resolved = [resolve_partial(partial) for partial in lookup.diagrams.values()]
    return sorted(resolved, key=lambda diag: diag.index)


def _should_vertical(specification: int, count: int) -> bool:
    """
    Returns true if we should return a vertical list of elements
    """
    if specification is None:
        return False
    else:
        return count >= specification


class ElementState:
    """
    State recorded for an individual pyparsing Element
    """

    # Note: this should be a dataclass, but we have to support Python 3.5
    def __init__(
        self,
        element: pyparsing.ParserElement,
        converted: EditablePartial,
        parent: EditablePartial,
        number: int,
        name: str = None,
        index: Optional[int] = None,
    ):
        #: The pyparsing element that this represents
        self.element = element  # type: pyparsing.ParserElement
        #: The name of the element
        self.name = name  # type: str
        #: The output Railroad element in an unconverted state
        self.converted = converted  # type: EditablePartial
        #: The parent Railroad element, which we store so that we can extract this if it's duplicated
        self.parent = parent  # type: EditablePartial
        #: The order in which we found this element, used for sorting diagrams if this is extracted into a diagram
        self.number = number  # type: int
        #: The index of this inside its parent
        self.parent_index = index  # type: Optional[int]
        #: If true, we should extract this out into a subdiagram
        self.extract = False  # type: bool
        #: If true, all of this element's children have been filled out
        self.complete = False  # type: bool

    def mark_for_extraction(
        self, el_id: int, state: "ConverterState", name: str = None, force: bool = False
    ):
        """
        Called when this instance has been seen twice, and thus should eventually be extracted into a sub-diagram
        :param force: If true, force extraction now, regardless of the state of this. Only useful for extracting the
        root element when we know we're finished
        """
        self.extract = True

        # Set the name
        if not self.name:
            if name:
                # Allow forcing a custom name
                self.name = name
            elif self.element.customName:
                self.name = self.element.customName
            else:
                unnamed_number = 1 if self.parent is None else state.generate_unnamed()
                self.name = "Unnamed {}".format(unnamed_number)

        # Just because this is marked for extraction doesn't mean we can do it yet. We may have to wait for children
        # to be added
        # Also, if this is just a string literal etc, don't bother extracting it
        if force or (self.complete and _worth_extracting(self.element)):
            state.extract_into_diagram(el_id)


class ConverterState:
    """
    Stores some state that persists between recursions into the element tree
    """

    def __init__(self, diagram_kwargs: dict = {}):
        #: A dictionary mapping ParserElement IDs to state relating to them
        self.first = {}  # type:  Dict[int, ElementState]
        #: A dictionary mapping ParserElement IDs to subdiagrams generated from them
        self.diagrams = {}  # type: Dict[int, EditablePartial[NamedDiagram]]
        #: The index of the next unnamed element
        self.unnamed_index = 1  # type:  int
        #: The index of the next element. This is used for sorting
        self.index = 0  # type:  int
        #: Shared kwargs that are used to customize the construction of diagrams
        self.diagram_kwargs = diagram_kwargs  # type:  dict

    def generate_unnamed(self) -> int:
        """
        Generate a number used in the name of an otherwise unnamed diagram
        """
        self.unnamed_index += 1
        return self.unnamed_index

    def generate_index(self) -> int:
        """
        Generate a number used to index a diagram
        """
        self.index += 1
        return self.index

    def extract_into_diagram(self, el_id: int):
        """
        Used when we encounter the same token twice in the same tree. When this happens, we replace all instances of that
        token with a terminal, and create a new subdiagram for the token
        """
        position = self.first[el_id]

        # Replace the original definition of this element with a regular block
        if position.parent:
            ret = EditablePartial.from_call(railroad.NonTerminal, text=position.name)
            if "item" in position.parent.kwargs:
                position.parent.kwargs["item"] = ret
            else:
                position.parent.kwargs["items"][position.parent_index] = ret

        # If the element we're extracting is a group, skip to its content but keep the title
        if position.converted.func == railroad.Group:
            content = position.converted.kwargs["item"]
        else:
            content = position.converted

        self.diagrams[el_id] = EditablePartial.from_call(
            NamedDiagram,
            name=position.name,
            diagram=EditablePartial.from_call(
                railroad.Diagram, content, **self.diagram_kwargs
            ),
            index=position.number,
        )
        del self.first[el_id]


def _worth_extracting(element: pyparsing.ParserElement) -> bool:
    """
    Returns true if this element is worth having its own sub-diagram. Simply, if any of its children
    themselves have children, then its complex enough to extract
    """
    children = element.recurse()
    return any(
        [hasattr(child, "expr") or hasattr(child, "exprs") for child in children]
    )


def _to_diagram_element(
    element: pyparsing.ParserElement,
    parent: Optional[EditablePartial],
    lookup: ConverterState = None,
    vertical: int = None,
    index: int = 0,
    name_hint: str = None,
) -> Optional[EditablePartial]:
    """
    Recursively converts a PyParsing Element to a railroad Element
    :param lookup: The shared converter state that keeps track of useful things
    :param index: The index of this element within the parent
    :param parent: The parent of this element in the output tree
    :param vertical: Controls at what point we make a list of elements vertical. If this is an integer (the default),
    it sets the threshold of the number of items before we go vertical. If True, always go vertical, if False, never
    do so
    :param name_hint: If provided, this will override the generated name
    :returns: The converted version of the input element, but as a Partial that hasn't yet been constructed
    """
    exprs = element.recurse()
    name = name_hint or element.customName or element.__class__.__name__

    # Python's id() is used to provide a unique identifier for elements
    el_id = id(element)

    # Here we basically bypass processing certain wrapper elements if they contribute nothing to the diagram
    if isinstance(element, (pyparsing.Group, pyparsing.Forward)) and (
        not element.customName or not exprs[0].customName
    ):
        # However, if this element has a useful custom name, we can pass it on to the child
        if not exprs[0].customName:
            propagated_name = name
        else:
            propagated_name = None

        return _to_diagram_element(
            element.expr,
            parent=parent,
            lookup=lookup,
            vertical=vertical,
            index=index,
            name_hint=propagated_name,
        )

    # If the element isn't worth extracting, we always treat it as the first time we say it
    if _worth_extracting(element):
        if el_id in lookup.first:
            # If we've seen this element exactly once before, we are only just now finding out that it's a duplicate,
            # so we have to extract it into a new diagram.
            looked_up = lookup.first[el_id]
            looked_up.mark_for_extraction(el_id, lookup, name=name_hint)
            return EditablePartial.from_call(railroad.NonTerminal, text=looked_up.name)

        elif el_id in lookup.diagrams:
            # If we have seen the element at least twice before, and have already extracted it into a subdiagram, we
            # just put in a marker element that refers to the sub-diagram
            return EditablePartial.from_call(
                railroad.NonTerminal, text=lookup.diagrams[el_id].kwargs["name"]
            )

    # Recursively convert child elements
    # Here we find the most relevant Railroad element for matching pyparsing Element
    # We use ``items=[]`` here to hold the place for where the child elements will go once created
    if isinstance(element, pyparsing.And):
        if _should_vertical(vertical, len(exprs)):
            ret = EditablePartial.from_call(railroad.Stack, items=[])
        else:
            ret = EditablePartial.from_call(railroad.Sequence, items=[])
    elif isinstance(element, (pyparsing.Or, pyparsing.MatchFirst)):
        if _should_vertical(vertical, len(exprs)):
            ret = EditablePartial.from_call(railroad.Choice, 0, items=[])
        else:
            ret = EditablePartial.from_call(railroad.HorizontalChoice, items=[])
    elif isinstance(element, pyparsing.Optional):
        ret = EditablePartial.from_call(railroad.Optional, item="")
    elif isinstance(element, pyparsing.OneOrMore):
        ret = EditablePartial.from_call(railroad.OneOrMore, item="")
    elif isinstance(element, pyparsing.ZeroOrMore):
        ret = EditablePartial.from_call(railroad.ZeroOrMore, item="")
    elif isinstance(element, pyparsing.Group):
        ret = EditablePartial.from_call(railroad.Group, item=None, label=name)
    elif isinstance(element, pyparsing.Empty) and not element.customName:
        # Skip unnamed "Empty" elements
        ret = None
    elif len(exprs) > 1:
        ret = EditablePartial.from_call(railroad.Sequence, items=[])
    elif len(exprs) > 0:
        ret = EditablePartial.from_call(railroad.Group, item="", label=name)
    else:
        # If the terminal has a custom name, we annotate the terminal with it, but still show the defaultName, because
        # it describes the pattern that it matches, which is useful to have present in the diagram
        terminal = EditablePartial.from_call(railroad.Terminal, element.defaultName)
        if element.customName is not None:
            ret = EditablePartial.from_call(
                railroad.Group, item=terminal, label=element.customName
            )
        else:
            ret = terminal

    # Indicate this element's position in the tree so we can extract it if necessary
    lookup.first[el_id] = ElementState(
        element=element,
        converted=ret,
        parent=parent,
        index=index,
        number=lookup.generate_index(),
    )

    i = 0
    for expr in exprs:
        # Add a placeholder index in case we have to extract the child before we even add it to the parent
        if "items" in ret.kwargs:
            ret.kwargs["items"].insert(i, None)

        item = _to_diagram_element(
            expr, parent=ret, lookup=lookup, vertical=vertical, index=i
        )

        # Some elements don't need to be shown in the diagram
        if item is not None:
            if "item" in ret.kwargs:
                ret.kwargs["item"] = item
            elif "items" in ret.kwargs:
                # If we've already extracted the child, don't touch this index, since it's occupied by a nonterminal
                if ret.kwargs["items"][i] is None:
                    ret.kwargs["items"][i] = item
                i += 1
        elif "items" in ret.kwargs:
            # If we're supposed to skip this element, remove it from the parent
            del ret.kwargs["items"][i]

    # If all this items children are none, skip this item
    if ret and (
        ("items" in ret.kwargs and len(ret.kwargs["items"]) == 0)
        or ("item" in ret.kwargs and ret.kwargs["item"] is None)
    ):
        return EditablePartial.from_call(railroad.Terminal, name)

    # Mark this element as "complete", ie it has all of its children
    if el_id in lookup.first:
        lookup.first[el_id].complete = True

    if (
        el_id in lookup.first
        and lookup.first[el_id].extract
        and lookup.first[el_id].complete
    ):
        lookup.extract_into_diagram(el_id)
        return EditablePartial.from_call(
            railroad.NonTerminal, text=lookup.diagrams[el_id].kwargs["name"]
        )
    else:
        return ret
