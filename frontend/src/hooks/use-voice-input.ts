import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

// The Web Speech API has no official TS lib entry (it's still
// non-standardized), so the constructor and event shapes are typed loosely
// here rather than pulling in a third-party @types package for a handful of
// fields we actually touch.
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as
    | (new () => SpeechRecognitionLike)
    | null;
}

const ERROR_MESSAGES: Record<string, string> = {
  "not-allowed": "Microphone access was denied. Allow it in your browser's site settings to use voice input.",
  "service-not-allowed": "Microphone access was denied. Allow it in your browser's site settings to use voice input.",
  "no-speech": "No speech detected. Try again.",
  "audio-capture": "No microphone was found. Check your device and try again.",
  network: "A network error interrupted voice input.",
};

interface UseVoiceInputOptions {
  /** Called with the full transcript accumulated since `start()` was called (final + interim). */
  onTranscript: (text: string) => void;
  lang?: string;
}

/** Real browser speech-to-text via the Web Speech API - permission prompt, live interim
 * transcript, and error handling are all native to `SpeechRecognition`; this hook just
 * wraps its callback-based API in React state. */
export function useVoiceInput({ onTranscript, lang }: UseVoiceInputOptions) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const [isListening, setIsListening] = useState(false);
  const isSupported = getSpeechRecognitionCtor() !== null;
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
    };
  }, []);

  const start = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      toast.error("Voice input isn't supported in this browser. Try Chrome or Edge.");
      return;
    }
    if (recognitionRef.current) return; // already listening

    const recognition = new Ctor();
    recognition.lang = lang || navigator.language || "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
    };
    recognition.onerror = (event) => {
      setIsListening(false);
      recognitionRef.current = null;
      // "aborted" fires on our own stop() call - not a real failure to report.
      if (event.error === "aborted") return;
      toast.error(ERROR_MESSAGES[event.error] ?? "Voice input failed. Please try again.");
    };
    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interimText += result[0].transcript;
      }
      onTranscriptRef.current(`${finalText} ${interimText}`.trim());
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      // start() throws if called while an instance is already running -
      // onstart/onend never fire in that case, so reset state directly.
      recognitionRef.current = null;
      setIsListening(false);
    }
  }, [lang]);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const toggle = useCallback(() => {
    if (isListening) stop();
    else start();
  }, [isListening, start, stop]);

  return { isListening, isSupported, start, stop, toggle };
}
