import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'math_text.dart';

typedef FigureBuilder = Widget Function(String id);

class VisualPanelView extends StatelessWidget {
  final Map<String, dynamic> panel;
  final FigureBuilder figureBuilder;
  const VisualPanelView(this.panel, {required this.figureBuilder, super.key});
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      if ((panel['title'] ?? '').toString().isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: MathText(panel['title']),
        ),
      if (panel['figure_id'] != null) figureBuilder(panel['figure_id']),
      if ((panel['text'] ?? '').toString().isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: MathText(panel['text']),
        ),
    ],
  );
}

class VisualGroupView extends StatelessWidget {
  final Map<String, dynamic> group;
  final FigureBuilder figureBuilder;
  const VisualGroupView(this.group, {required this.figureBuilder, super.key});
  @override
  Widget build(BuildContext context) {
    final panels = (group['panels'] as List).cast<Map<String, dynamic>>();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if ((group['caption'] ?? '').toString().isNotEmpty)
            MathText(group['caption']),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = math.min(
                group['columns'] as int? ?? 2,
                math.max(1, (constraints.maxWidth / 220).floor()),
              );
              final width =
                  (constraints.maxWidth - (columns - 1) * 16) / columns;
              return Wrap(
                spacing: 16,
                runSpacing: 16,
                children: [
                  for (final panel in panels)
                    SizedBox(
                      width: width,
                      child: VisualPanelView(
                        panel,
                        figureBuilder: figureBuilder,
                      ),
                    ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}
