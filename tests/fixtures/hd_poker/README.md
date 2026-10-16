# HD Poker glyph regression samples

Small, lossless crops from HD Poker 1.9.5 at a 3812 × 2138 client size,
captured locally during calibration on 2026-10-16. They contain card symbols
and amount text only. No full screenshots, names, chat, wallet or account details
are included. `source_frame` identifiers are local provenance, not downloadable files.

`labels.json` separates training and test samples from different source frames.
Adjacent frames are correlated; this is a regression set, not a population accuracy
estimate. Some test crops intentionally remain unknown with the limited templates.
Sample `test-21.png` contains no visible amount and must remain unknown.
Other test labels describe the visible symbol/text: an accepted reading must match;
rejection is allowed. The test enforces a minimum accepted count as well as zero
wrong accepted values. Whole-text examples cover touching bold amount characters;
digit examples also test amounts that were not taught as complete strings.
