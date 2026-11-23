/* SPDX-License-Identifier: AGPL-3.0-or-later */
#ifndef VIETNAV_HUD_ARROW_H
#define VIETNAV_HUD_ARROW_H
#include <stdint.h>
#define VN_ARROW_SIDE 32u
#define VN_ARROW_PIXELS (VN_ARROW_SIDE * VN_ARROW_SIDE)
#define VN_ARROW_RECORD (4u + VN_ARROW_PIXELS)
#define VN_ARROW_MODEL_MAX (12u + 256u * VN_ARROW_RECORD)
extern const unsigned char vn_arrow_model[];
extern const unsigned vn_arrow_model_size;
struct vn_arrow_result {
    unsigned icon, group, score_squared_milli, margin_squared_milli;
};
/* All decoder work is statically bounded (128x128); no heap/libjpeg/libm.
 * Calls must be serialized: picojpeg has global work buffers. */
int vn_arrow_model_valid(const unsigned char *model, unsigned size);
int vn_arrow_vector_gray(const unsigned char *pixels, unsigned width, unsigned height,
                         unsigned char out[VN_ARROW_PIXELS]);
int vn_arrow_match(const unsigned char *model, unsigned model_size,
                   const unsigned char *jpeg, unsigned jpeg_size,
                   struct vn_arrow_result *out);
#endif
