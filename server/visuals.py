"""Stable asset identities keep pictures attached to the correct option/panel."""
from pathlib import Path


def choose_path(asset, redraw=False):
    return (asset.redrawn_image or asset.original_image) if redraw else (
        asset.original_image or asset.redrawn_image)


def public_assets(question):
    return [v.model_dump(include={"id", "caption", "description"}) for v in question.visuals]


def referenced_ids(question):
    panels = [p for g in question.visual_groups for p in g.panels]
    panels += [p for t in question.tables for c in t.cells for p in c.panels]
    return {p.figure_id for p in panels if p.figure_id}


def sync_paths(question):
    question.original_images = [v.original_image for v in question.visuals if v.original_image]
    question.redrawn_images = [v.redrawn_image for v in question.visuals if v.redrawn_image]
    question.svg_files = [v.svg_file for v in question.visuals if v.svg_file]


def safe_path(folder: Path, relative: str):
    path = (folder / relative).resolve()
    if not relative or not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise RuntimeError("配图资源缺失，未导出不完整试卷。")
    return path


def merge_continuation(prior, continued):
    """Page-local IDs and crop indices must be rebased before concatenation."""
    occupied = {v.id for v in prior.visuals}
    mapping = {}
    for asset in continued.visuals:
        candidate = asset.id
        while candidate in occupied:
            candidate += "_next"
        occupied.add(candidate)
        mapping[asset.id] = candidate
        asset.id = candidate
        if asset.source_region is not None:
            asset.source_region += len(prior.figures)
    panels = [p for g in continued.visual_groups for p in g.panels]
    panels += [p for t in continued.tables for c in t.cells for p in c.panels]
    for panel in panels:
        if panel.figure_id:
            panel.figure_id = mapping[panel.figure_id]
    prior.visuals.extend(continued.visuals)
