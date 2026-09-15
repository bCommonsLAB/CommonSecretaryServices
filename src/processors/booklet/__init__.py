"""
@fileoverview Booklet package - Image pipeline for the b*coop Projektheft

@description
Building blocks used by BookletProcessor: theme tokens, image loading and
cropping, duotone toning and watermarks. Pure Pillow, no browser, no LLM.

@module processors.booklet

@exports
- tokens: Theme colours and page geometry
- images: load_image, crop_to_frame, readiness
- duotone: apply_duotone
- watermark: add_too_small_band, placeholder_image

@usedIn
- src.processors.booklet_processor: BookletProcessor
"""
