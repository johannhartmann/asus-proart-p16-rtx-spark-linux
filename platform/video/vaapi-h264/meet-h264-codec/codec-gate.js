// Runs only in the dedicated P16 Meet Chrome profile, before Meet's own code.
// Keep changes to the standard WebRTC negotiation API; do not rewrite SDP.
(() => {
  if (globalThis.__p16MeetH264CodecGate || !globalThis.RTCPeerConnection ||
      !globalThis.RTCRtpTransceiver || !globalThis.RTCRtpReceiver) return;

  const pcProto = RTCPeerConnection.prototype;
  const transceiverProto = RTCRtpTransceiver.prototype;
  const nativeSetPreferences = transceiverProto.setCodecPreferences;
  if (typeof nativeSetPreferences !== 'function' ||
      typeof RTCRtpReceiver.getCapabilities !== 'function') return;
  const counters = {attempts: 0, applied: 0, errors: 0};
  Object.defineProperty(globalThis, '__p16MeetH264CodecGate', {
    value: Object.freeze({counters}), configurable: false,
  });

  function preferredVideoCodecs() {
    const codecs = RTCRtpReceiver.getCapabilities('video')?.codecs ?? [];
    const h264 = codecs.filter(codec => codec.mimeType.toLowerCase() === 'video/h264');
    if (!h264.length) return [];
    h264.sort((left, right) =>
      Number(/profile-level-id=42e0/i.test(right.sdpFmtpLine ?? '')) -
      Number(/profile-level-id=42e0/i.test(left.sdpFmtpLine ?? '')));
    // Keep retransmission and error repair for the selected media codec.
    const repair = codecs.filter(codec =>
      /video\/(rtx|red|ulpfec|flexfec-03)/i.test(codec.mimeType));
    return [...h264, ...repair];
  }

  function enforce(transceiver) {
    if (!sendsVideo(transceiver) || transceiver.stopped) return;
    const codecs = preferredVideoCodecs();
    if (!codecs.length) return;
    counters.attempts++;
    try {
      nativeSetPreferences.call(transceiver, codecs);
      counters.applied++;
    } catch (error) {
      counters.errors++;
      console.warn('P16 Meet H.264 codec preference failed', error);
    }
  }

  function sendsVideo(transceiver) {
    return transceiver?.sender?.track?.kind === 'video' ||
      (transceiver?.receiver?.track?.kind === 'video' &&
       /send/.test(transceiver.direction));
  }

  function enforceAll(pc) {
    for (const transceiver of pc.getTransceivers()) enforce(transceiver);
  }

  const nativeAddTransceiver = pcProto.addTransceiver;
  pcProto.addTransceiver = function (...args) {
    const transceiver = nativeAddTransceiver.apply(this, args);
    enforce(transceiver);
    return transceiver;
  };
  const nativeAddTrack = pcProto.addTrack;
  pcProto.addTrack = function (...args) {
    const sender = nativeAddTrack.apply(this, args);
    enforceAll(this);
    return sender;
  };
  const nativeCreateOffer = pcProto.createOffer;
  pcProto.createOffer = function (...args) {
    enforceAll(this);
    return nativeCreateOffer.apply(this, args);
  };
  const nativeCreateAnswer = pcProto.createAnswer;
  pcProto.createAnswer = function (...args) {
    enforceAll(this);
    return nativeCreateAnswer.apply(this, args);
  };
  const nativeSetLocalDescription = pcProto.setLocalDescription;
  pcProto.setLocalDescription = function (...args) {
    if (!args.length || !args[0] || args[0].type === 'offer' ||
        args[0].type === 'answer') enforceAll(this);
    return nativeSetLocalDescription.apply(this, args);
  };
  transceiverProto.setCodecPreferences = function (codecs) {
    if (!sendsVideo(this)) {
      return nativeSetPreferences.call(this, codecs);
    }
    const h264 = preferredVideoCodecs();
    if (!h264.length) return nativeSetPreferences.call(this, codecs);
    counters.attempts++;
    try {
      const result = nativeSetPreferences.call(this, h264);
      counters.applied++;
      return result;
    } catch (error) {
      counters.errors++;
      console.warn('P16 Meet H.264 codec preference failed', error);
      return nativeSetPreferences.call(this, codecs);
    }
  };
})();
