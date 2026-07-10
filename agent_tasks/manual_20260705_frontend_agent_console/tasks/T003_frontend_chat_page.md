# T003

Add a frontend page or section for real-time answer output.

UI requirements:
- engine selector
- text input
- start button
- cancel button
- main answer area
- secondary diagnostics area

The main answer area must subscribe to answer_delta events and append visible answer text.
It must not render file-tail logs as the main content.
