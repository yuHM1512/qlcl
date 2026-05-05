"""Verify all patches were applied correctly."""

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

checks = [
    ('/api/qc/upload-sp-image', '/api/qc/upload-sp-image' in content),
    ('image_path in INSERT SQL', 'image_path)' in content),
    ('d.get("image_path") in VALUES', 'd.get("image_path")' in content),
]

for label, ok in checks:
    print(f"  [{'OK' if ok else 'FAIL'}] main.py: {label}")

with open('templates/qc_input_sp.html', 'r', encoding='utf-8') as f:
    content2 = f.read()

checks2 = [
    ('.camera-section CSS', '.camera-section' in content2),
    ('blockImagePaths JS var', 'blockImagePaths' in content2),
    ('cameraInput_ HTML', 'cameraInput_' in content2),
    ('image_path in defects.push', 'image_path: blockImagePaths' in content2),
]

for label, ok in checks2:
    print(f"  [{'OK' if ok else 'FAIL'}] template: {label}")

print("\nAll checks passed!" if all(c[1] for c in checks + checks2) else "\nSome checks FAILED!")
