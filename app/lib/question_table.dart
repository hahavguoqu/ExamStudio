import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'math_text.dart';
import 'visual_group.dart';

/// Native preview of the same cells/spans exported to Word.
class QuestionTableView extends StatelessWidget {
  final Map<String, dynamic> table;
  final FigureBuilder? figureBuilder;
  const QuestionTableView(this.table, {this.figureBuilder, super.key});

  @override
  Widget build(BuildContext context) {
    final cells = (table['cells'] as List).cast<Map<String, dynamic>>();
    final columns = table['columns'] as int;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if ((table['caption'] as String? ?? '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: MathText(table['caption']),
            ),
          LayoutBuilder(
            builder: (context, constraints) {
              final width = math.max(constraints.maxWidth, columns * 85.0);
              return SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: SizedBox(
                  width: width,
                  child: _CellGrid(
                    table: table,
                    children: [
                      for (final cell in cells)
                        Padding(
                          padding: const EdgeInsets.all(10),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              MathText(cell['text'] as String? ?? ''),
                              for (final panel
                                  in (cell['panels'] as List? ?? []))
                                VisualPanelView(
                                  Map<String, dynamic>.from(panel),
                                  figureBuilder:
                                      figureBuilder ??
                                      (_) => const Text('配图暂不可用'),
                                ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _CellGrid extends MultiChildRenderObjectWidget {
  final Map<String, dynamic> table;
  const _CellGrid({required this.table, required super.children});

  @override
  RenderObject createRenderObject(BuildContext context) => _GridRender(table);

  @override
  void updateRenderObject(BuildContext context, _GridRender renderObject) {
    renderObject.table = table;
    renderObject.markNeedsLayout();
  }
}

class _CellParentData extends ContainerBoxParentData<RenderBox> {}

class _GridRender extends RenderBox
    with
        ContainerRenderObjectMixin<
          RenderBox,
          ContainerBoxParentData<RenderBox>
        >,
        RenderBoxContainerDefaultsMixin<
          RenderBox,
          ContainerBoxParentData<RenderBox>
        > {
  Map<String, dynamic> table;
  final List<Rect> borders = [];
  _GridRender(this.table);

  @override
  void setupParentData(RenderBox child) {
    if (child.parentData is! ContainerBoxParentData<RenderBox>) {
      child.parentData = _CellParentData();
    }
  }

  @override
  void performLayout() {
    final cells = (table['cells'] as List).cast<Map<String, dynamic>>();
    final heights = List<double>.filled(table['rows'] as int, 40);
    final count = table['columns'] as int;
    final ratios = ((table['column_widths'] as List?) ?? []).isEmpty
        ? List<double>.filled(count, 1)
        : (table['column_widths'] as List)
              .map((v) => (v as num).toDouble())
              .toList();
    final total = ratios.fold(0.0, (a, b) => a + b);
    final xs = <double>[0];
    for (final ratio in ratios) {
      xs.add(xs.last + constraints.maxWidth * ratio / total);
    }
    final children = <RenderBox>[];
    RenderBox? child = firstChild;
    for (final cell in cells) {
      final current = child!;
      children.add(current);
      current.layout(
        BoxConstraints.tightFor(
          width:
              xs[(cell['column'] as int) + (cell['column_span'] as int? ?? 1)] -
              xs[cell['column'] as int],
        ),
        parentUsesSize: true,
      );
      final row = cell['row'] as int;
      final span = cell['row_span'] as int? ?? 1;
      if (span == 1) heights[row] = math.max(heights[row], current.size.height);
      child = childAfter(current);
    }
    // A spanning cell must also fit; later growth can only add space.
    for (var i = 0; i < cells.length; i++) {
      final row = cells[i]['row'] as int;
      final span = cells[i]['row_span'] as int? ?? 1;
      final available = heights
          .sublist(row, row + span)
          .fold(0.0, (a, b) => a + b);
      final extra = math.max(0.0, children[i].size.height - available) / span;
      for (var r = row; r < row + span; r++) {
        heights[r] += extra;
      }
    }
    final offsets = <double>[0];
    for (final height in heights) {
      offsets.add(offsets.last + height);
    }
    borders.clear();
    for (var i = 0; i < cells.length; i++) {
      final cell = cells[i];
      final row = cell['row'] as int, col = cell['column'] as int;
      final end = row + (cell['row_span'] as int? ?? 1);
      final rect = Rect.fromLTWH(
        xs[col],
        offsets[row],
        xs[col + (cell['column_span'] as int? ?? 1)] - xs[col],
        offsets[end] - offsets[row],
      );
      borders.add(rect);
      (children[i].parentData as ContainerBoxParentData<RenderBox>).offset =
          Offset(
            rect.left,
            rect.top + (rect.height - children[i].size.height) / 2,
          );
    }
    size = constraints.constrain(Size(constraints.maxWidth, offsets.last));
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final pen = Paint()
      ..color = const Color(0xffaeb6c2)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (final rect in borders) {
      context.canvas.drawRect(rect.shift(offset).deflate(.5), pen);
    }
    defaultPaint(context, offset);
  }

  @override
  bool hitTestChildren(BoxHitTestResult result, {required Offset position}) =>
      defaultHitTestChildren(result, position: position);
}
