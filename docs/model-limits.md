# Limits of the models in use

Measured directly through ViLao (`https://api.vilao.ai/v1`), not taken from outside documentation.
Method: a script sends numbered images or a test clip and checks what comes back. Measure again when
the model or the provider changes. Each section carries its measurement date.

## Image model: `gpt-image-2` (`AIC_IMAGE_MODEL`, `AIC_IMAGE_API=edits`, measured 2026-11-15)

Measured on the `/images/edits` endpoint with numbered test cards.

| Item | Result |
| --- | --- |
| Input images per request | Every size of list returns HTTP 200 (tried 1, 5, 11, 16, 17, 30, 40), but only the **first 10 images** are used. Asking for "the last input card" returned card 5 with 5 inputs and card 10 with 11, 16, 30 and 40 inputs. Images after the 10th are dropped without an error, so put the most important images first |
| Output images per request | **1 image**. `n: 3` is rejected: "'n' must be an integer from 1 to 1" |
| Time | 26 to 85 seconds per request (more input images tend to take longer) |
| Portrait size | `size: "1024x1792"` or `size: "9:16"` gives **941x1672**, which is exactly 9:16; `EDITS_SIZE` in `keyframes.py` sends `1024x1792`. The size `1024x1536` gives 1024x1536, which is 2:3 and would have to be cropped (`_to_vertical` still crops any image that is not 9:16). With no `size`, or with `aspect_ratio: "9:16"` only, the result is also 1024x1536: `aspect_ratio` has no effect |
| Price | Not measured: the response has no cost field. Read it from the ViLao balance |

The table below was measured on the old model `veo/gemini-3.1-flash-image` (2026-11-05 and
2026-11-06) and does not apply to `gpt-image-2`; it is kept only for a comparison if the model is
switched back.

| Item | Result |
| --- | --- |
| Input images per request | Accepts and uses all **30 images** (tried 5, 14, 15, 20, 30; the output reflects every image). 31 to 40 images return "upstream overloaded", but that error also appeared when retrying 30 images, so it does not prove a limit above 30 |
| Output images per request | **1 image**. Sending `n: 3` or asking for "4 images" still returns 1 (one `choice`, one link) |
| Time | 60 to 80 seconds per request |
| Portrait size | `size: "1024x1792"` gives a 768x1376 image. `size: "9:16"` fails; do not use it |
| Price | 50 VND per request |

## Video model: `xai/grok-imagine-video` (declared as `dw/xai/grok-imagine-video`, measured 2026-11-06)

| Item | Result |
| --- | --- |
| First-frame image (image-to-video) | Exactly **1 image**. The clip starts from it and keeps the composition |
| Clip length for image-to-video | `seconds` from **1 to 15** (5, 8, 10, 12 and 15 all ran; 16, 20 and 30 were rejected: "seconds must be from 1 to 15"). `/models` lists only 6 and 15, but the other values still work |
| Resolution | 704x1280 with a first-frame image, 720x1280 with reference images only. `quality: "720p"` makes no difference |
| Reference images (`reference_images`) | At most **7 images**. 8 images are rejected: "at most 7 reference images" |
| Clip length with reference images | At most **10 seconds** (10 s ran; 12 s and 15 s jobs report "Invalid request") |
| First-frame image together with reference images | **Rejected** |
| Reference images without a first frame | The video uses the reference look but rebuilds the whole scene; the composition is not kept |
| Audio | Every clip carries an AAC audio track made by Grok, even when the prompt says "no sound". Grok can be told to speak a Vietnamese sentence, with lip movement that follows it |
| Price | 999 VND per request, independent of the number of seconds |

**Usage rule (settled 2026-11-14):** the price is per request, not per second or per resolution, so
every clip request asks for the longest and sharpest output the model accepts: `seconds = 15`
(`CLIP_SECONDS` in `clips.py`), 9:16 with the keyframe as the first frame (704x1280, no higher
setting exists). Never ask for a shorter or smaller clip to save money; trim it after generation.
Measure again when the model or the provider changes.

Consequence: a clip uses one of two modes, the keyframe as the first frame (in use, up to 15 seconds)
or up to 7 reference images (up to 10 seconds). The product must be correct already in the keyframe.

## TTS: `bh2/tts-1` (measured 2026-11-06)

| Item | Result |
| --- | --- |
| Input | `input` is text, with `voice` (`giongadam.mp3`, `hamy.mp3`, `tiendat.mp3`, `huuduc.mp3`, `kimoanh.mp3`, `maichi.mp3`, `auto`) and `response_format` (`mp3` or `wav` according to `/models`) |
| Output | One audio file. mp3: 24 kHz, mono, about 49 kbps |
| Length that ran | 400 characters (84 Vietnamese words) gave **28.9 seconds** of audio in 11 seconds; 80 characters gave 5.6 seconds |
| Maximum length | **Not measured**: the service was unstable; requests of 800 characters or more returned `503 upstream request failed` after 120 seconds, but an 80-character request failed at the same time. Measure again when the service is stable |
| wav format | Not measured for the same reason |
| Price | 20 VND per request |

## Writer and review models (`AIC_WRITER_MODEL`, `AIC_REVIEW_MODEL`)

One model per variable, no fallback; an error names the model that failed. Image-count limit not
measured. Reached through an OpenAI-compatible endpoint (`AIC_SCREENING_BASE_URL`); the endpoint
used so far was 9Router. The brief sends every product photo of the page (up to 9 so far) and still
works. No `max_tokens` is set (`build_client_registry` leaves it out unless a caller passes
`max_output_tokens`), and the brief writer sends `reasoning_effort: "none"`, because a reasoning
model that spends its tokens on thinking cut the output short when a limit was set. The steps that build their client with `reasoning_effort=None`
(hooks, shortening, voice pick, reference picks, clip check) send none. Measure again when the model or the endpoint changes.
