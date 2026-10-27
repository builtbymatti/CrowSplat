#include <metal_stdlib>
#include <SwiftUI/SwiftUI_Metal.h>
using namespace metal;

// The window's ground: brushed anodized metal with survey contour lines
// drifting across it, lit from the top and, faintly, from the pointer.
// The same shader as the brand page, kept at low strength so the controls
// on top stay the thing you read.

static float hash(float2 p) {
    p = fract(p * float2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

static float noise(float2 p) {
    float2 i = floor(p), f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + float2(1, 0)), u.x),
               mix(hash(i + float2(0, 1)), hash(i + float2(1, 1)), u.x), u.y);
}

static float fbm(float2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + 17.1; a *= 0.5; }
    return v;
}

[[ stitchable ]] half4 instrument(float2 position, half4 color, float2 size, float time,
                                  float2 pointer, float strength) {
    float2 uv = position / size;
    uv.y = 1.0 - uv.y;                                  // light comes from the top
    float aspect = size.x / size.y;
    float2 p = float2(uv.x * aspect, uv.y);

    // Brushed grain: noise stretched hard along x, two scales.
    float brush = noise(float2(p.x * 3.0, p.y * 520.0)) * 0.6 + noise(float2(p.x * 9.0, p.y * 1300.0)) * 0.4;

    // Contour lines of a slowly drifting height field.
    float f = fbm(p * 2.4 + float2(time * 0.012, 0.0));
    float k = fract(f * 11.0);
    float line = 1.0 - smoothstep(0.0, 0.045, min(k, 1.0 - k));

    float3 base = float3(color.rgb);
    float3 col = base + float3(brush) * 0.03 * strength + float3(0.725, 0.741, 0.706) * line * 0.055 * strength;
    col *= 0.8 + 0.2 * smoothstep(0.0, 1.0, uv.y);

    float2 m = float2(pointer.x * aspect, 1.0 - pointer.y);
    float md = length(p - m);
    col += float3(0.906, 0.914, 0.886) * 0.04 * strength * exp(-md * md * 5.0);

    // Fine grain so the gradient never bands.
    col += (hash(position + fract(time) * 91.7) - 0.5) * 0.025;
    return half4(half3(col), color.a);
}
