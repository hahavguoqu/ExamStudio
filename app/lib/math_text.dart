import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';

class MathText extends StatelessWidget {
  final String text;
  final TextStyle? style;
  const MathText(this.text, {super.key, this.style});
  @override
  Widget build(BuildContext context) {
    final pattern = RegExp(
      r'\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]',
    );
    final spans = <InlineSpan>[];
    var cursor = 0;
    for (final match in pattern.allMatches(text)) {
      if (match.start > cursor) {
        spans.add(TextSpan(text: text.substring(cursor, match.start)));
      }
      final formula =
          match.group(1) ?? match.group(2) ?? match.group(3) ?? match.group(4)!;
      spans.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: Math.tex(
            formula,
            textStyle: style ?? const TextStyle(fontSize: 16),
            onErrorFallback: (_) => Text(formula, style: style),
          ),
        ),
      );
      cursor = match.end;
    }
    if (cursor < text.length) spans.add(TextSpan(text: text.substring(cursor)));
    return Text.rich(
      TextSpan(children: spans),
      style:
          style ??
          const TextStyle(fontSize: 16, height: 1.9, color: Color(0xff252a33)),
    );
  }
}
