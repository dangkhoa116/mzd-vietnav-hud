# picojpeg

Source: https://github.com/richgel999/picojpeg

Pinned commit: `8ab33a909b4115ace4a952b7ffcb64c350f9298d`.
Author: Rich Geldreich. Public domain; upstream also offers MIT licensing.
See the original source/header notices and README.md alongside this file.
Line endings normalized to LF; trailing whitespace removed. Local changes:

- Separate pointer increments from reads in four RGB conversion assignments
  to remove undefined sequencing reported by GCC.
- Validate baseline SOS spectral/successive fields instead of ignoring them.
- Disable the unused upstream `findEOI` helper; Vietnav checks the input JPEG
  envelope and bounds the callback before decoding.
- Replace negative-value constant left shifts with defined negated positive
  shifts (same numeric extension offsets), required by current GCC/UBSan.

Vietnav restricts inputs to 8192 bytes, baseline JPEG, at most 128×128 pixels,
uses no allocation and serializes decoding under the native transport lock.
