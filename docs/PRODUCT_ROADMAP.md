# Product Roadmap

## Started prototype: Question paper import / question extraction

Teacher uploads an image/PDF of a question paper. The system extracts question numbers, question text, marks, and possible sub-questions into draft Questions. The teacher must review and edit the drafted Questions before saving.

Important: this is not simple OCR only. It needs document understanding, question segmentation, mark detection, and teacher confirmation.

Prototype status: Started in TA-W1-028B. Current foundation supports safe question-paper upload, deterministic/mock draft extraction, draft question review/edit/select, and teacher-confirmed creation of real Questions. Real Codex/OCR extraction is not enabled by default.

## Future extension: Voice command assistant

Teacher can use voice commands for common UI actions, such as upload, next item, approve selected, go to review, and export result.

Status: Future extension, not implemented now.
