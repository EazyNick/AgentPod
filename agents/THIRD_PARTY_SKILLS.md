# Third-Party Skills

`spec-inspect/.claude/skills/` and `apply-verify/.claude/skills/`에 아래 5개 스킬을
[arsallls/claude-network-skills](https://github.com/arsallls/claude-network-skills)에서
그대로 가져와 vendoring했습니다(런타임에 clone하지 않고 저장소에 커밋 — DUT/LAN 전용
네트워크에서도 항상 사용 가능하도록).

- `network-config-validation`
- `network-bgp-diagnostics`
- `network-interface-health`
- `netmiko-ssh-automation`
- `cisco-ios-patterns`

(원본 저장소의 홈랩 전용 스킬 4개 — `homelab-network-setup`, `homelab-vlan-segmentation`,
`homelab-pihole-dns`, `homelab-wireguard-vpn` — 는 DUT 테스트 용도와 무관해 제외했습니다.)

## License

MIT License, Copyright (c) 2026 Arsal Sajjad.

```
Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```
