Ad rail images.

Name the file after the slot it fills:

    left.png     shows in the left rail
    right.png    shows in the right rail

.png .jpg .jpeg .gif .webp .svg .avif all work. The rail is 160x600, and the
image is scaled to fit inside it, so any aspect ratio renders without
stretching -- a tall skyscraper just fills it best.

Restart the app after adding a file. Slots are resolved at startup so that
rendering a page never touches the filesystem.

Optional, in .env:

    AD_LEFT_HREF=https://example.com    makes the image a link
    AD_LEFT_ALT=Sponsor name            alt text for screen readers

With no file here, the slot renders a dashed placeholder box instead.
