import { useCallback, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, ZoomIn, ZoomOut, Download, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ImageLightboxProps {
  src: string;
  alt?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.5;

/**
 * Full-screen image viewer: zoom (wheel or buttons), drag-to-pan once
 * zoomed, download, and three equivalent ways to close (X button, Escape,
 * clicking the backdrop) - the last two come from Radix Dialog for free.
 */
export function ImageLightbox({ src, alt = "Image", open, onOpenChange }: ImageLightboxProps) {
  const [zoom, setZoom] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const reset = useCallback(() => {
    setZoom(1);
    setPosition({ x: 0, y: 0 });
  }, []);

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const zoomIn = () => setZoom((z) => Math.min(MAX_ZOOM, +(z + ZOOM_STEP).toFixed(2)));
  const zoomOut = () =>
    setZoom((z) => {
      const next = Math.max(MIN_ZOOM, +(z - ZOOM_STEP).toFixed(2));
      if (next === MIN_ZOOM) setPosition({ x: 0, y: 0 });
      return next;
    });

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    if (e.deltaY < 0) zoomIn();
    else zoomOut();
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (zoom <= MIN_ZOOM) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: position.x, origY: position.y };
    setIsDragging(true);
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setPosition({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
  };
  const stopDragging = () => {
    dragRef.current = null;
    setIsDragging(false);
  };

  const handleDownload = () => {
    const a = document.createElement("a");
    a.href = src;
    const safeName = alt.trim().replace(/[^\w.-]+/g, "-").toLowerCase();
    a.download = safeName || "image";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          className="fixed inset-0 z-50 flex flex-col outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
          aria-describedby={undefined}
          // Close-on-click is the default for the whole surface - the
          // toolbar and the image itself opt out via stopPropagation below,
          // rather than this trying to enumerate every "empty" region
          // (toolbar padding, gaps between buttons, letterboxing around the
          // image) as its own special case.
          onClick={() => handleOpenChange(false)}
        >
          <Dialog.Title className="sr-only">{alt}</Dialog.Title>

          <div
            className="flex items-center justify-end gap-1.5 p-3"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-white hover:bg-white/10 hover:text-white"
              onClick={zoomOut}
              disabled={zoom <= MIN_ZOOM}
              aria-label="Zoom out"
            >
              <ZoomOut className="h-4 w-4" />
            </Button>
            <span className="min-w-[3.5rem] text-center text-sm tabular-nums text-white/80">
              {Math.round(zoom * 100)}%
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-white hover:bg-white/10 hover:text-white"
              onClick={zoomIn}
              disabled={zoom >= MAX_ZOOM}
              aria-label="Zoom in"
            >
              <ZoomIn className="h-4 w-4" />
            </Button>
            {zoom > MIN_ZOOM && (
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 text-white hover:bg-white/10 hover:text-white"
                onClick={reset}
                aria-label="Reset zoom"
              >
                <RotateCcw className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-white hover:bg-white/10 hover:text-white"
              onClick={handleDownload}
              aria-label="Download image"
            >
              <Download className="h-4 w-4" />
            </Button>
            <Dialog.Close asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 text-white hover:bg-white/10 hover:text-white"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </Button>
            </Dialog.Close>
          </div>

          <div
            className="flex flex-1 items-center justify-center overflow-hidden px-4 pb-6"
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={stopDragging}
            onMouseLeave={stopDragging}
          >
            <img
              src={src}
              alt={alt}
              className="max-h-full max-w-full select-none object-contain"
              style={{
                transform: `scale(${zoom}) translate(${position.x / zoom}px, ${position.y / zoom}px)`,
                cursor: zoom > MIN_ZOOM ? (isDragging ? "grabbing" : "grab") : "default",
                transition: isDragging ? "none" : "transform 150ms ease-out",
              }}
              draggable={false}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
