# Third-party notices

Online PDF reading uses [Mozilla PDF.js](https://github.com/mozilla/pdf.js),
Apache-2.0 licensed, via the pinned `pdfjs-dist` package. The upstream JavaScript,
worker, viewer styles, fonts and license are served locally from the installed
package; no PDF content is sent to an external PDF viewer service.

The PPT renderer uses [PptxGenJS](https://github.com/gitbrent/PptxGenJS), MIT licensed.
Copyright (c) 2015-present Brent Ely. Its full upstream license is distributed
in `ppt/node_modules/pptxgenjs/LICENSE` when installed with `npm ci --prefix ppt`.
The project renderer uses the published library API and does not copy its source.

Reading interaction design references the publicly described selection, note and
source-navigation workflows of [小绿鲸](https://www.xljsci.com/). No proprietary
code, branding or interface assets from that product are incorporated.

Dynamic browser reading uses [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp),
Apache-2.0 licensed. The installed package retains the upstream license and notices.
Browser paper searching also uses the installed Playwright library directly to launch local Chrome.

The default embedding model is [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small),
MIT licensed. Downloaded model files and their license are retained in the model directory.

The reading-memory design references the locally supplied
`ai_memory_system-master/ai_memory_system-master` project (its README credits Spark
and declares MIT). Layered memory, explicit curation, review and Markdown portability
informed the implementation. No source code or personal-memory templates were copied.
