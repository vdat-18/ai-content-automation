# Design: from brief to video ad, with images as the anchor

Status: implemented (see the README). This file is kept as the original design; some details have
changed since: the video follows a person from the user's photos, there is a voice-over, keyframes are
cropped to 9:16, there is no separate script review (the brief writer checks its own work), every
shot gets its own reference photo (section 4 below no longer applies: no two shots share one while
the pool allows) and a video has 1 to 7 shots, each filmed for 15 seconds. Goal: a short video ad stitched
from several clips where **the product and the setting look the same in every clip** and match the
real product.

## 1. Why images come before video

The video model only makes short clips, and every generation "invents" things again. Given text alone,
the product changes colour and shape, label text changes, and the setting shifts between clips. The
cure: **every clip starts from a reviewed keyframe image** (image-to-video), and every keyframe is made
from the **real product photos** plus a **reference setting image**. Images are much cheaper than
video, so a mistake is fixed at the image stage instead of burning video money.

## 2. Overall flow

```
product + real photos + product data + reference images + user idea + creative rules
  → [1] Concept + storyboard (one agent call)
  → [2] Master keyframe: the product placed in the reference setting        ← you review it
  → [3] Keyframes of the remaining shots, made from the master and the real product photos
  → [4] Automatic check of every keyframe (right product, right setting); regenerate if wrong
  → [5] Each keyframe → one short video clip (image-to-video)
  → [6] Stitch clips + text + voice-over into one video
```

Every step stores its result so a step can be rerun on its own.

## 3. What the brief reads

| Input | Used for |
|---|---|
| Product data (title, price, sales, rating, specifications, description) | Selling angle and true details; no invented features |
| Real product photos | Colour, shape, details; also the source images for the image model |
| Reference images and their descriptions (written by the screening model) | Settings to borrow |
| The user's idea (optional) | Creative direction, which the agent enriches |
| **Creative rules** | Opening-hook rules, TikTok Shop banned words, visual rules, accumulated lessons |
| **Product type** | A way of filming that suits the type (household goods differ from cosmetics) |

## 4. How many reference images per product

Recommendation: **one main reference image per video; when a product gets several videos, a different
image for each video.**

- **Inside one video, use one setting.** The clips must show the same room and the same light to
  stitch into one continuous video. Several different references in one video make the setting jump,
  and the image model accepts only a limited number of input images per call.
- **Between videos of the same product, change the reference image.** That is the source of variety
  for N ads (together with changing the selling angle, the audience and the hook).
- **Controlled exception:** one extra reference image is allowed for a shot or two that needs another
  setting (for example a close-up of use), but the default is one.

To pick the main image for each video: take the most different candidates, let the agent choose the one
that fits the product and the idea, and drop images already used by earlier videos of the same product.

## 5. The brief becomes a concept and a storyboard

A brief now contains:

- **Concept:** selling angle, audience, hook, tone, the chosen main reference image, and a description
  of the video's "world" (setting, light, colours).
- **A storyboard of 4 to 6 shots**, each with: role (hook, problem, demo, benefit, call to action), a
  description of the picture, the **keyframe prompt**, the **motion prompt** for the clip (camera, short
  action), duration, on-screen text and the spoken line.

The principle stays: the agent does everything in one call, and the user may add ideas and edit.

## 6. Keeping product and setting consistent

1. **Master keyframe first.** Make one image that places the real product in the reference setting (the
   image model receives the product photos and the setting image as input). The user approves it before
   anything else is made: if this image is right, the whole video is right.
2. **The remaining shots are generated from the master keyframe**, with the real product photos sent
   again on every call, changing only the camera angle and the action.
3. **An automatic check with the screening model** after each keyframe: against the real product
   photos (colour, shape, quantity, label text) and against the master keyframe (same setting, same
   light). If wrong, regenerate a few times at most, then tell the user.
4. **Clips:** each clip is made from exactly one keyframe (image-to-video). If the video model supports
   first and last frames, the next shot's keyframe can serve as the last frame for a smooth transition.

(The first version avoided human faces. That has since changed: a person from the user's photo
library appears in the ads, and every image is checked against that photo.)

## 7. Approval points (save money)

1. Approve the storyboard (text, cheap).
2. **Approve the master keyframe** (image, cheap). This is the most important gate.
3. The other keyframes are checked automatically; the user only skims and deletes bad shots.
4. Only then are clips made (expensive).

## 8. What had to be known before coding

- **The image and video models available** (names, capabilities). Minimum requirements: an image model
  that takes **several input images** (product and setting) for editing, and a video model that
  supports **image-to-video**. Measured limits are in [model-limits.md](model-limits.md).
- Aspect ratio (9:16 for TikTok), video length, number of shots, maximum clip length of the model.
- Voice-over and music: done at the stitching step.
