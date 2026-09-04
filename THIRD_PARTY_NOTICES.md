# Third-Party Notices

Pixal itself is licensed under the [Pixal Source-Available License](LICENSE).
These notices cover components Pixal bundles, drives or downloads — they are
**not** covered by that license and carry their own terms.

Pixal includes or produces a browser bundle containing the following third-party
software, and adapts published values and prompt practice from a handful of
upstream workflows. These notices apply to those components, not to Pixal
itself — except where noted: the Anima and FLUX.2 Klein entries are
non-commercial, and the values ported from Anima live in `server.py` and
`templates/anima.json`.

- **ComfyUI** — GPL-3.0. Pixal is an independent program that communicates with
  ComfyUI over its HTTP API as a separate process, and does not redistribute it;
  the installer downloads it. Per [ComfyUI's licensing guidance](https://github.com/Comfy-Org/ComfyUI/discussions/14346),
  independent tools that only connect to ComfyUI are not bound by its GPL.
  **Anything placed in `custom_nodes/` is a derivative work and must be
  GPL-3.0** — see [CONTRIBUTING.md](CONTRIBUTING.md).
- **Python** (embeddable build, redistributed in the installer) — Copyright
  Python Software Foundation — PSF License Agreement.
- **llama-cpp-python** / **llama.cpp**, **ffmpeg**, and the node packs the
  installer fetches (ComfyUI-GGUF, RES4LYF) retain their own upstream licenses;
  none are redistributed here.

- React and React DOM 19.2.0 — Copyright Meta Platforms, Inc. and affiliates — MIT License.
- Phosphor Icons for React 2.1.10 — Copyright Phosphor Icons contributors — MIT License.
- Three.js r160 — Copyright 2010–2023 Three.js Authors — MIT License. The rebuild
  source is retained at `web/vendor/three.module.js`.
- esbuild 0.28.2 — Copyright Evan Wallace and contributors — MIT License. esbuild
  is a build-time dependency and is not required to run the checked-in bundle.
- [Amazing Z-Image Workflow v4](https://github.com/martin-rizzo/AmazingZImageWorkflow)
  by Martin Rizzo — Unlicense. Pixal's Z-Image Turbo execution profile adapts
  its hand-tuned split-sigma schedule.
- [ComfyUI-Fantastic-MiniMaxH3-PromptBuilder](https://github.com/Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder)
  — MIT License. Pixal's H3 brief writing (the three-field structure, header
  rules, and `<d>` dialogue tags in `server.py`) follows the MiniMax prompt-guide
  practice this node pack established. The pack itself is a separate ComfyUI
  custom node, not part of Pixal — install it in ComfyUI for hand-driven H3
  prompting alongside Pixal's chat-driven flow.
- [Anima](https://huggingface.co/circlestone-labs/Anima) by CircleStone Labs —
  **CircleStone Labs Non-Commercial License v1.2**, and, as a stated Derivative
  Model of NVIDIA's Cosmos-Predict2-2B-Text2Image, also the NVIDIA Open Model
  License Agreement. `templates/anima.json` is a port of ComfyUI's own shipped
  blueprint for the model, and the `ANIMA_*` constants in `server.py` follow the
  model card's quality and negative tag scaffolding. The weights are not
  redistributed here; the installee downloads them. The restriction lands on the
  model, not on the pictures: the license claims no ownership of Outputs and
  permits their commercial use.
- [FLUX.2 Klein 9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B)
  by Black Forest Labs — **FLUX Non-Commercial License v2.1**. It drives both
  Klein edit lanes: the masked-inpaint lane (`templates/klein_inpaint.json`,
  a port of the F4 group of geoahmed's flux2_klein_ultimate_v2.1 workflow) and
  the whole-frame instruction lane (`templates/klein_edit.json`, a port of
  Comfy-Org's shipped image_flux2_klein_image_edit_9b_distilled template),
  and the `KLEIN_*`
  constants in `server.py` hold its step-distilled schedule. The weights are
  not redistributed here; the Hugging Face repository is gated, and fetching
  them there means accepting the license. The restriction lands on the model,
  not on the pictures: the license claims no ownership of Outputs and permits
  their commercial use.

The NVIDIA, Lightricks, and MiniMax marks (`web/src/lib/BrandMarks.jsx`) —
shown beside the LTX and MiniMax H3 engines and on the settings About panel —
are trademarks of their respective owners, used to identify the technology
publishers. Path data follows the lobe-icons set (MIT). The ComfyUI logotype
on the About panel is the ComfyUI project's own mark, used to credit the
platform Pixal drives.

- **Krea** — the Krea marks (`brand/vendor/krea-favicon-192.png`,
  `site/assets/krea.png`) are Krea's own, shown beside the Krea 2 engine
  entries on the site to identify the model's publisher.
- **simple-icons** — the OpenAI, Anthropic and Moonshot AI SVGs under
  `site/assets/` come from the simple-icons set (CC0 1.0 Universal); the
  marks they depict remain the property of their respective owners.

Dependency versions are recorded in `package-lock.json`. Source distributions in
`node_modules` retain their upstream license files when installed with `npm ci`.

## Trademarks and brand marks

Pixal's interface, its installer and its website show the names and logos of
other companies — the model authors, the engines, the chat providers and the
tools Pixal works alongside. Where those marks are stored in this repository
they live under `site/assets/` and `brand/vendor/`.

**Every such name and logo is the property of its respective owner**, and no
claim of ownership is made here. They appear for one reason only: to identify
factually which model, engine or service a given feature uses, so that a
person can tell what is running. Their presence is nominative use — it is not
sponsorship, endorsement, affiliation or partnership, claimed or implied, in
either direction. Where a mark is reproduced it is reproduced unmodified, and
where an upstream project publishes brand guidelines those are the terms that
govern, not this file.

The Pixal Source-Available License grants no rights in any of these marks.
Section 3(d) of that license — which forbids removing or altering attribution
— applies to them as it does to Pixal's own marks: they may not be restyled,
recoloured or repurposed to suggest a relationship that does not exist.

If you own one of these marks and would prefer it removed, changed or
attributed differently, write to hello@getpixal.com and it will be
done.

## Fonts

Pixal redistributes the following webfont files, subset to Latin, under
`site/fonts/` for the website and `web/fonts/` for the app. Copyright lines
below are read from the `name` table of the
shipped files themselves, not transcribed from upstream. All three families
are licensed under the **SIL Open Font License, Version 1.1**, whose text is
reproduced in full below as that licence requires.

- **Geist** (`geist-400-n-latin.woff2`, `geist-600-n-latin.woff2`,
  `geist-variable-latin.woff2`) —
  Copyright 2024 The Geist Project Authors
  (https://github.com/vercel/geist-font) — SIL OFL 1.1.
- **JetBrains Mono** (`jetbrains-mono-500-n-latin.woff2`) —
  Copyright 2020 The JetBrains Mono Project Authors
  (https://github.com/JetBrains/JetBrainsMono) — SIL OFL 1.1.
- **Syne** (`syne-600-n-latin.woff2`, `syne-700-n-latin.woff2`,
  `syne-variable-latin.woff2`) —
  Copyright 2019 The Syne Project Authors
  (https://gitlab.com/bonjour-monde/fonderie/syne-typeface) — SIL OFL 1.1.

The Geist and Syne variable fonts in `web/fonts/` are bundled inside the
installer, alongside this notice, so the local app does not depend on a font
CDN. The files in `site/fonts/` are served by the website. None is sold on its
own. All remain under the OFL and travel with this notice. Pixal ships them
unmodified apart from Latin subsetting.

## SIL Open Font License, Version 1.1 text

Copyright applies as stated per family above.

    PREAMBLE

    The goals of the Open Font License (OFL) are to stimulate worldwide
    development of collaborative font projects, to support the font creation
    efforts of academic and linguistic communities, and to provide a free and
    open framework in which fonts may be shared and improved in partnership
    with others.

    The OFL allows the licensed fonts to be used, studied, modified and
    redistributed freely as long as they are not sold by themselves. The
    fonts, including any derivative works, can be bundled, embedded,
    redistributed and/or sold with any software provided that any reserved
    names are not used by derivative works. The fonts and derivatives,
    however, cannot be released under any other type of license. The
    requirement for fonts to remain under this license does not apply to any
    document created using the fonts or their derivatives.

    DEFINITIONS

    "Font Software" refers to the set of files released by the Copyright
    Holder(s) under this license and clearly marked as such. This may include
    source files, build scripts and documentation.

    "Reserved Font Name" refers to any names specified as such after the
    copyright statement(s).

    "Original Version" refers to the collection of Font Software components as
    distributed by the Copyright Holder(s).

    "Modified Version" refers to any derivative made by adding to, deleting,
    or substituting -- in part or in whole -- any of the components of the
    Original Version, by changing formats or by porting the Font Software to a
    new environment.

    "Author" refers to any designer, engineer, programmer, technical writer or
    other person who contributed to the Font Software.

    PERMISSION & CONDITIONS

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of the Font Software, to use, study, copy, merge, embed, modify,
    redistribute, and sell modified and unmodified copies of the Font
    Software, subject to the following conditions:

    1) Neither the Font Software nor any of its individual components, in
    Original or Modified Versions, may be sold by itself.

    2) Original or Modified Versions of the Font Software may be bundled,
    redistributed and/or sold with any software, provided that each copy
    contains the above copyright notice and this license. These can be
    included either as stand-alone text files, human-readable headers or in
    the appropriate machine-readable metadata fields within text or binary
    files as long as those fields can be easily viewed by the user.

    3) No Modified Version of the Font Software may use the Reserved Font
    Name(s) unless explicit written permission is granted by the corresponding
    Copyright Holder. This restriction only applies to the primary font name as
    presented to the users.

    4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
    Software shall not be used to promote, endorse or advertise any Modified
    Version, except to acknowledge the contribution(s) of the Copyright
    Holder(s) and the Author(s) or with their explicit written permission.

    5) The Font Software, modified or unmodified, in part or in whole, must be
    distributed entirely under this license, and must not be distributed under
    any other license. The requirement for fonts to remain under this license
    does not apply to any document created using the Font Software.

    TERMINATION

    This license becomes null and void if any of the above conditions are not
    met.

    DISCLAIMER

    THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
    COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
    COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
    INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
    DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM OTHER
    DEALINGS IN THE FONT SOFTWARE.

## MIT License text

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
