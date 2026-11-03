# Specification

This file is the project-level index for package specifications. Detailed public contracts live beside their owning packages to keep updates local and avoid duplicating the source of truth.

## HTML-to-Markdown Converter

`MarkdownConverter` converts HTML to Markdown. Its API, converter pipeline, built-in conversions, extension points, and limitations are specified in [the Markdown Converter specification](./src/fairybrowser/html_analysis/markdown_converter/SPECIFICATION.md).

## HTML Simplification

`HTMLSimplifier` provides rule-based HTML simplification. Its rule and protection behavior, along with the `simplify_html_for_playwright` and `clean_html` helper contracts, are specified in [the HTML Simplifier specification](./src/fairybrowser/html_analysis/html_simplifier/SPECIFICATION.md).
