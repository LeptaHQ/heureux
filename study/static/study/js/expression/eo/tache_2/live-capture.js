// Integrate fractional input samples across worklet blocks (typically 44.1 or 48 kHz).
// Output stays silent: the microphone must never play through the local speakers.
class FrenchLiveCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new DataView(new ArrayBuffer(2048)); // 64 ms of 16 kHz PCM
    this.pos = 0;
    this.weight = 0;
    this.sum = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      for (const sample of channel) {
        let remaining = 16000;
        while (remaining > 0) {
          const take = Math.min(remaining,sampleRate-this.weight);
          this.sum += sample*take; this.weight += take; remaining -= take;
          if (this.weight === sampleRate) {
            const x = Math.min(1,Math.max(-1,this.sum/sampleRate));
            this.frame.setInt16(this.pos,Math.round(x*(x < 0 ? 32768 : 32767)),true);
            this.pos += 2; this.sum = this.weight = 0;
            if (this.pos === this.frame.byteLength) {
              this.port.postMessage(this.frame.buffer,[this.frame.buffer]);
              this.frame = new DataView(new ArrayBuffer(2048)); this.pos = 0;
            }
          }
        }
      }
    }
    return true;
  }
}
registerProcessor("french-live-pcm", FrenchLiveCapture);
