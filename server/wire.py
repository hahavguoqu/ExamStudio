"""Small API-only schemas. Persistent task models remain backward compatible."""
from copy import deepcopy
from pydantic import create_model
from schemas import Question, Paper, VisualAsset


def subset(name, source, names, replacements=None):
    replacements = replacements or {}
    return create_model(name, **{
        key: (replacements.get(key, source.model_fields[key].annotation), deepcopy(source.model_fields[key]))
        for key in names.split()
    })


ReadVisual = subset("ReadVisual", VisualAsset, "id caption description source_region")
NewVisual = subset("NewVisual", VisualAsset, "id caption description")
COMMON = "number stem kind points options parts tables visual_groups warnings"
ReadQuestion = subset("ReadQuestion", Question, COMMON + " content_role figures visuals continued", {"visuals": list[ReadVisual]})
ReadPaper = subset("ReadPaper", Paper, "title instructions questions warnings", {"questions": list[ReadQuestion]})
NewQuestion = subset("NewQuestion", Question,
    COMMON + " visuals answer solution core supporting method difficulty knowledge reference_ids", {"visuals": list[NewVisual]})


def output_type(schema):
    return {Paper: ReadPaper, Question: NewQuestion}.get(schema, schema)


def compact_schema(schema):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in ("title", "default")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return clean(output_type(schema).model_json_schema())
