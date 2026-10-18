#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 uSize;
    float uRadius;
    float uBorderWidth;
    float uPhase;
    vec4 uColor;
    float uCoreRadius;
    float uTailLength;
    float uHaloRadius;
    float uDpr;
    float uOutset;
};

const float PI = 3.14159265358979323846;

// Signed distance to a rounded rectangle centered at origin with hb-extent
// b and corner radius r (IQ's sdRoundRect).
float sdRoundRect(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// Map a point to its perimeter coordinate t in [0,1) on the rounded rect
// border, using the nearest point on the 8-segment boundary. Segment 0 is the
// top edge starting at the top-left corner arc end.
vec2 perimeterCoord(vec2 p, vec2 hb, float r, float perimeter) {
    float w = hb.x * 2.0;
    float h = hb.y * 2.0;
    float straightX = max(w - 2.0 * r, 0.0);
    float straightY = max(h - 2.0 * r, 0.0);
    float arc = (PI * 0.5) * r;
    float seg0 = straightX;
    float seg1 = arc;
    float seg2 = straightY;
    float seg3 = arc;
    float seg4 = straightX;
    float seg5 = arc;
    float seg6 = straightY;
    float seg7 = arc;

    // Corner arc centers.
    vec2 c0 = vec2(-hb.x + r, -hb.y + r); // top-left
    vec2 c1 = vec2( hb.x - r, -hb.y + r); // top-right
    vec2 c2 = vec2( hb.x - r,  hb.y - r); // bottom-right
    vec2 c3 = vec2(-hb.x + r,  hb.y - r); // bottom-left

    float bestDist = 1e9;
    float bestT = 0.0;

    // Segment 0: top straight (left -> right), y = -hb.y.
    {
        vec2 d = p - vec2(-hb.x + r, -hb.y);
        float t = clamp(d.x / max(straightX, 1e-6), 0.0, 1.0);
        vec2 q = vec2(-hb.x + r + t * straightX, -hb.y) - p;
        float dist = length(q);
        float per = (seg0 * t) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 1: top-right arc (angle -90..0 around c1).
    {
        vec2 d = p - c1;
        float ang = atan(d.y, d.x);
        float a = clamp(ang, -PI * 0.5, 0.0);
        vec2 q = c1 + r * vec2(cos(a), sin(a));
        float dist = length(q - p);
        float frac = (a + PI * 0.5) / (PI * 0.5);
        float per = (seg0 + seg1 * frac) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 2: right straight (top -> bottom), x = hb.x.
    {
        vec2 d = p - vec2(hb.x, -hb.y + r);
        float t = clamp(d.y / max(straightY, 1e-6), 0.0, 1.0);
        vec2 q = vec2(hb.x, -hb.y + r + t * straightY) - p;
        float dist = length(q);
        float per = (seg0 + seg1 + seg2 * t) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 3: bottom-right arc (angle 0..PI/2 around c2).
    {
        vec2 d = p - c2;
        float ang = atan(d.y, d.x);
        float a = clamp(ang, 0.0, PI * 0.5);
        vec2 q = c2 + r * vec2(cos(a), sin(a));
        float dist = length(q - p);
        float frac = a / (PI * 0.5);
        float per = (seg0 + seg1 + seg2 + seg3 * frac) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 4: bottom straight (right -> left), y = hb.y.
    {
        vec2 d = p - vec2(hb.x - r, hb.y);
        float t = clamp(-d.x / max(straightX, 1e-6), 0.0, 1.0);
        vec2 q = vec2(hb.x - r - t * straightX, hb.y) - p;
        float dist = length(q);
        float per = (seg0 + seg1 + seg2 + seg3 + seg4 * t) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 5: bottom-left arc (angle PI/2..PI around c3).
    {
        vec2 d = p - c3;
        float ang = atan(d.y, d.x);
        float a = clamp(ang, PI * 0.5, PI);
        vec2 q = c3 + r * vec2(cos(a), sin(a));
        float dist = length(q - p);
        float frac = (a - PI * 0.5) / (PI * 0.5);
        float per = (seg0 + seg1 + seg2 + seg3 + seg4 + seg5 * frac) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 6: left straight (bottom -> top), x = -hb.x.
    {
        vec2 d = p - vec2(-hb.x, hb.y - r);
        float t = clamp(-d.y / max(straightY, 1e-6), 0.0, 1.0);
        vec2 q = vec2(-hb.x, hb.y - r - t * straightY) - p;
        float dist = length(q);
        float per = (seg0 + seg1 + seg2 + seg3 + seg4 + seg5 + seg6 * t) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    // Segment 7: top-left arc (angle PI..3PI/2 around c0).
    {
        vec2 d = p - c0;
        float ang = atan(d.y, d.x);
        float a = clamp(ang, PI, PI * 1.5);
        vec2 q = c0 + r * vec2(cos(a), sin(a));
        float dist = length(q - p);
        float frac = (a - PI) / (PI * 0.5);
        float per = (seg0 + seg1 + seg2 + seg3 + seg4 + seg5 + seg6 + seg7 * frac) / perimeter;
        if (dist < bestDist) { bestDist = dist; bestT = per; }
    }
    return vec2(bestT, bestDist);
}

void main() {
    // Pixel in card logical coordinates. The ShaderEffect is expanded by
    // uOutset on every side so the halo can spill outside the card edge.
    vec2 p = qt_TexCoord0 * (uSize + 2.0 * uOutset) - uOutset;
    vec2 hb = uSize * 0.5;
    float r = min(uRadius, min(hb.x, hb.y));
    float sdf = sdRoundRect(p - hb, hb, r);

    float w = hb.x * 2.0;
    float h = hb.y * 2.0;
    float straightX = max(w - 2.0 * r, 0.0);
    float straightY = max(h - 2.0 * r, 0.0);
    float arc = (PI * 0.5) * r;
    float perimeter = 2.0 * straightX + 2.0 * straightY + 4.0 * arc;

    vec2 pc = perimeterCoord(p - hb, hb, r, perimeter);
    float t = pc.x;          // perimeter coordinate 0..1
    float borderDist = pc.y; // distance to the border centerline

    // Border mask: only pixels inside the border band contribute.
    float borderMask = exp(-(borderDist * borderDist) / (uBorderWidth * uBorderWidth * 0.25));

    // Ring distance along the perimeter: signed forward distance from the
    // current phase to this pixel's perimeter position.
    float s = fract(t - uPhase + 0.5) - 0.5; // -0.5..0.5, negative = behind
    float pxDist = s * perimeter;            // in pixels along the border

    // Core: bright point at the light position.
    float core = exp(-(pxDist * pxDist) / (uCoreRadius * uCoreRadius));
    // Tail: smooth falloff behind the point.
    float tail = pxDist < 0.0
        ? exp((pxDist) / max(uTailLength, 1.0))
        : 0.0;
    // Halo: low-alpha glow around the border edge, driven by the SDF so it
    // spills outside the card (never clipped by the border band mask).
    float halo = exp(-(sdf * sdf) / (uHaloRadius * uHaloRadius));

    // The light point and tail hug the border centerline; the halo glows
    // around the whole edge and is NOT multiplied by borderMask.
    vec3 col = uColor.rgb * ((core + tail * 0.85) * borderMask + halo * 0.24);
    float alpha = (core + tail * 0.65) * borderMask + halo * 0.18;

    fragColor = vec4(col, alpha) * qt_Opacity;
}
