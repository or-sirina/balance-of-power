shader_type canvas_item;
render_mode blend_mul, unshaded;

void fragment() {
    vec3 original = texture(TEXTURE, UV).rgb;
    float gray = dot(original, vec3(11.0, 16.0, 5.0)) / 32.0;
    float relative = clamp(gray / (210.0 / 255.0), 0.0, 1.0);
    float shade = 0.72 + 0.28 * pow(relative, 1.5);
    COLOR = vec4(vec3(shade), 1.0);
}
