# A docstring explains itself and cites no ADR. The citation moves to a marker comment

A docstring in `src/kapps_semantic_middleware/` states what the code does and why, **in its own
words**. It names no ADR.

The ADR numbers move to a marker comment on the first line of the body, directly under the
docstring:

```python
def prune_southbound(class_spec, *, ogm, interface_root=..., cache=None):
    """Return a copy of ``class_spec`` with each parameter's protocol metadata removed.

    A peer that learned a broker address and a topic could drive the device directly, and
    bypass every check this middleware performs. So the shape is cut before any data is read,
    and the ontology decides what gets cut.
    """
    # ADR: 0028
```

For a module, the marker goes directly under the module docstring, above the imports.

## Why

### An IDE tooltip is the most-read documentation this project has, and a citation wastes it

Hovering a name in VS Code or PyCharm shows the docstring. That popup is where a domain expert
meets this library, and it is small. `(ADR 0028)` costs a line of it and answers nothing: the
reader still does not know what happens, and now has a homework assignment.

The marker is a comment, so **no tooltip renders it**. `__doc__` is what an IDE reads, and a
comment is not part of `__doc__`. The reader gets the whole popup for the explanation.

### A citation is not an explanation, and it hid the fact that some docstrings had none

Writing `(ADR 0023)` feels like justification. It is a pointer to justification, which is a
different thing, and it let a docstring look finished while explaining nothing. Several read
like *"this is done because ADR 0017 says so"* — true, unhelpful, and unreadable to anyone
outside this repository. Forbidding the citation forces the sentence that was missing.

### Chasing an ADR is expensive for a human and cheap for an agent

An ADR is a record of a decision, with its alternatives and the argument between them. That is
the right document to read when you are **changing** the decision, and the wrong one to read
when you are trying to use a function. Thirty-five records, two directories, two numbering
sequences that both start at 0001 — following one citation is a minute, and there were 143 of
them in this package.

An agent pays almost none of that cost. It greps.

### Traceability was the real requirement, and a marker keeps it

The reason the citations existed is worth keeping: it must stay possible to ask *"which code
implements ADR 0028?"*. The marker answers that better than prose did, because it is uniform
and machine-readable:

```bash
grep -rn "# ADR: " src/ | grep 0028
```

Prose could not be searched that way — a reference might read `ADR 0028`, `ADR 0028's`, `see
ADR 0028`, or `per ADR 0028`. The marker has exactly one form.

The source ships in the wheel, so this works for a consumer who installed the package, not only
inside this checkout.

## Consequences

- **`src/` only.** `demo/transferunits/` keeps its citations. The demo exists to teach how the
  decisions play out, and a reader there is being sent to the ADRs on purpose.
- **Markdown is unaffected.** `CONTEXT.md`, the ADRs themselves, `mqtt-payloads.md` and every
  README cite freely. This rule is about the tooltip, and prose documents have no tooltip.
- **A docstring may still name a decision in words** where the words are the point — "the
  ontology decides what is pruned, not the registry" is the content of ADR 0028 and belongs in
  the docstring. What it may not do is stand in the place of that sentence with a number.
- The marker is not a runtime object. It sets no attribute and costs nothing at import.
- **Not enforced by a test yet.** The convention is new, and a guard belongs with the next pass
  over this package rather than in the commit that establishes it.

## What was rejected

**A `__adr__` dunder attribute, set by a decorator or assigned after each definition.** It is
machine-readable in a stronger sense — `func.__adr__` needs no grep. Rejected on cost against
benefit: a module docstring cannot be decorated, so modules would need a second mechanism; a
decorator on 79 definitions is a large diff for metadata; and an attribute assigned after a
definition drifts from the definition it describes. Nothing in this project consumes such an
attribute today, and a grep marker serves the one query that is actually asked.

**Leaving the citations and shortening the docstrings instead.** This mistakes the symptom.
The tooltip is not too long because docstrings are verbose; it is too long because it carries
homework.
