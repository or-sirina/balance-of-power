shader_type canvas_item;
render_mode blend_mul, unshaded;

uniform sampler2D land_mask : filter_nearest;

void fragment() {
 // Original relief image supplies the terrain. Neighbour samples emphasize
 // its existing ridges without inventing elevation or strategic information.
 float height = dot(texture(TEXTURE, UV).rgb, vec3(11.0,16.0,5.0))/32.0;
 vec2 texel = TEXTURE_PIXEL_SIZE * 1.5;
 float west = dot(texture(TEXTURE, UV - vec2(texel.x, 0.0)).rgb, vec3(11.0,16.0,5.0))/32.0;
 float east = dot(texture(TEXTURE, UV + vec2(texel.x, 0.0)).rgb, vec3(11.0,16.0,5.0))/32.0;
 float north = dot(texture(TEXTURE, UV - vec2(0.0, texel.y)).rgb, vec3(11.0,16.0,5.0))/32.0;
 float south = dot(texture(TEXTURE, UV + vec2(0.0, texel.y)).rgb, vec3(11.0,16.0,5.0))/32.0;
 float directional = (west-east)*0.9 + (north-south)*0.7;
 float relative = clamp(height / (210.0 / 255.0), 0.0, 1.0);
 float shade = clamp(0.66 + 0.34*pow(relative,1.4) + directional, 0.48, 1.0);
 float land = texture(land_mask, UV).r;
 COLOR = vec4(vec3(mix(1.0,shade,land)), 1.0);
}
