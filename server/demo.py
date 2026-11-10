"""Explicitly labelled hand-authored fixture. Never impersonates an AI run."""
from pathlib import Path

import documents
import store
from schemas import Paper, Question


def create_demo():
    task = store.create("数学工作室体验试卷", "convert",
                        {"layout": "clean", "figures": "both", "difficulty": "same",
                         "creativity": "variation", "requirements": ""})
    folder = store.task_dir(task["id"])
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 450">
    <path d="M130 340 L470 340 L130 110 Z" fill="none" stroke="black" stroke-width="2"/>
    <path d="M130 320 L150 320 L150 340" fill="none" stroke="black" stroke-width="1.5"/>
    <text x="105" y="365" font-size="24">A</text><text x="477" y="360" font-size="24">B</text>
    <text x="106" y="100" font-size="24">C</text><text x="292" y="372" font-size="20">4</text>
    <text x="100" y="231" font-size="20">3</text></svg>'''
    svg_file, png_file = documents.render_svg(svg, folder, "demo-triangle")
    paper = Paper(title="数学工作室体验试卷",
                  instructions=["本卷为人工编写的功能演示材料，不是 AI 生成结果。"],
                  questions=[
        Question(id="demo01", stem="解方程 $x^2-5x+6=0$。", kind="解答题", points=6,
                 core=["一元二次方程"], supporting=["因式分解"], answer="$x=2$ 或 $x=3$",
                 solution="因式分解得 $(x-2)(x-3)=0$，因此 $x=2$ 或 $x=3$。",
                 knowledge="利用零乘积性质求解可因式分解的一元二次方程。", provenance="人工编写的演示题"),
        Question(id="demo02", stem="如图，在 $\\triangle ABC$ 中，$\\angle A=90^\\circ$，$AB=4$，$AC=3$。求 $BC$ 的长。",
                 kind="解答题", points=6, original_images=[png_file], redrawn_images=[png_file], svg_files=[svg_file],
                 core=["勾股定理"], answer="$BC=5$", solution="由勾股定理，$BC^2=AB^2+AC^2=16+9=25$。因为长度为正，所以 $BC=5$。",
                 knowledge="直角三角形的斜边平方等于两条直角边的平方和。", provenance="人工编写的演示题"),
        Question(id="demo03", stem="求函数 $y=x^2-4x+7$ 的最小值，并写出取得最小值时 $x$ 的值。",
                 kind="解答题", points=8, core=["二次函数最值"], supporting=["配方法"],
                 answer="当 $x=2$ 时，最小值为 $3$。",
                 solution="配方得 $y=(x-2)^2+3$。由于 $(x-2)^2\\geq 0$，故 $y\\geq 3$，等号在 $x=2$ 时成立。",
                 knowledge="通过配方把二次函数表示为顶点式，结合平方非负判断最值。", provenance="人工编写的演示题")
    ])
    exports = [documents.export_docx(folder, paper, task["options"]),
               documents.export_docx(folder, paper, task["options"], True),
               documents.export_resources(folder, paper)]
    return store.update(task["id"], status="completed", stage="演示材料 · 未调用 AI",
                        progress=100, demo=True, paper=paper.model_dump(), exports=exports)
