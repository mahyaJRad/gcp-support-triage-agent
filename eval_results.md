## Extraction baseline comparison (entities vs Stack Overflow tags)

Micro-averaged precision/recall/F1 over 300 tickets, scored against each ticket's tags as a free gold standard (same documents for both).

| Extractor | Precision | Recall | F1 |
|-----------|:---------:|:------:|:--:|
| Cloud Natural Language API | 0.174 | 0.778 | 0.285 |
| spaCy `en_core_web_sm` | 0.333 | 0.566 | 0.419 |
