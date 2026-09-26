# Audit K: the foundation (codec, net, bot, transcript, runner)

Date: 2026-09-26. Base: `main` at `9288671`. Auditor: worker K (opus), read-only.

Scope: `src/mscts/codec/` (wire, framing, schema, packets, schemas/, regen),
`src/mscts/net.py`, `src/mscts/bot.py`, `src/mscts/transcript.py`,
`src/mscts/runner.py`, and their tests. Not in scope: `compare.py` (J) and
`adapters/pumpkin.py` (H), which were being built in parallel.

Method: read every module and test against `docs/PLAN.md`, `CONTEXT.md` and
ADR-0001…0005; disassembled the vanilla 26.3 network classes from the cached
jar (`javap -c` on `server-26.3.jar` inside the bundler, sha1 `33680f5f…`,
and Netty 4.2.16) to settle "what does vanilla do"; ran throwaway probes
over localhost fakes; ran 90 mutations through `scripts/mutate.py`
against the whole unit tier; and ran the reference tier once. Probe scripts
and raw mutation output are in the session scratchpad (not committed);
every command and result that a finding rests on is quoted below.

## Executive summary

The foundation is in good shape where it has been tested. 70 of the 90
mutations were killed. The runner's cleanup holds under exceptions,
timeouts and cancellation, with no leaked process on any path. Encode
strictness (exact field names, ints reject bool, String bounds) is solid.
Nothing here is corrupting a Verdict **today**, because no Run exists yet.
But three defects will corrupt Verdicts or Measurements as soon as the M2
Run and the M4 join are built on top, and no current test would notice:

1. **Readiness trusts whoever answers at the Endpoint** (high). `running()`
   declared an Instance ready 3 ms after launch, before its process had even
   started Python, because another server held the port. For vanilla the
   exposure is the whole ~10 s boot, not just the bind moment. A Scenario
   would then run against the wrong server and `instance.startup` would read
   3 ms.
2. **Received Packets are stamped when the Bot takes them, not when they
   arrive** (high). A status response the server wrote 0.1 ms after the
   request was recorded 300.8 ms later, because the Bot did something else
   for 300 ms before calling `recv`. Every Transcript-derived Measurement,
   and any window-scoped Comparison, inherits this bias. The test called
   `..._both_stamped_on_arrival` passes only because every test reads
   before the data arrives.
3. **A Candidate's undecodable packet leaves no trace, and has no Verdict**
   (high). `recv` raises `CodecError` and records nothing. CONTEXT defines
   `error` as "the harness failed, or the Reference could not run", so a
   Candidate that sends garbage has no defined outcome. If the M2 Run maps
   exceptions to `error`, then `compliance = matches / (scenarios − errors)`
   gives a Candidate that sends garbage a **higher** score than one that sends
   a wrong value. The bytes G3 needs for a readable Divergence are gone too.

Among the rest, the most relevant findings are:

- VarInt/VarLong decoding returns out-of-range values where vanilla
  truncates (`ff ff ff ff 7f` → 30064771071; vanilla reads −1).
- `send` records a packet that never left, then raises
  `ConnectionResetError`.
- `Packet` is frozen but unhashable, and its fields are mutable. This is
  directly relevant to J.
- `FrameDecoder.feed` can silently misdecode the frame right after
  `login_compression` (it is test-only today: delete it).
- A negative compression threshold is not "off" as it is in vanilla.
- `scripts/mutate.py` reports a mistyped test path as `KILLED`.
- A double cancellation leaves an unclosed subprocess transport. The unit
  test's `eventually` wait hides the ResourceWarning.
- 20 surviving mutations: 12 are missing tests and 8 are equivalent.

## Findings

Severity: **critical** = wrong Verdicts/Measurements in current use; **high** =
will produce them once M2/M4 are built on this, with no test failing;
**medium** = a contract, strictness or tooling defect with a plausible path to
a wrong result; **low** = hygiene, dead code, naming, docs. Finding ids are
H#, MD# and L#. Plain M2, M4 and M7 always mean PLAN milestones. Mutation
ids (W, F, S, P, N, B, T, R, G) are listed in the [mutation log](#mutation-log).

No critical findings: nothing consumes these modules in a Run yet.

### H1 (high). Readiness accepts any server that answers at the Endpoint

- **Location**: `src/mscts/runner.py:215-227` (`_ready_ns`) with
  `src/mscts/bot.py:131-156` (`status_probe`); `free_port`
  `src/mscts/runner.py:52-66`.
- **Evidence**: an asyncio "impostor" answered status with protocol 777 on
  port P, and `running()` launched `fake_server.py P --never-listen` (a
  process that never listens) with `ready=status_probe(TARGET)`:

  ```
  $ .venv/bin/python -W error scratchpad/probe_runner.py
  P17 running() yielded a ready Instance (pid 32327) after 0.003 s, although its
  process never listens: the probe was answered by the impostor on port 44723
  ```

  Polling starts at launch, so any listener on the port during the ~7–10 s
  that vanilla spends before it binds (`docs/research/2026-09-26-runner.md`)
  makes the Instance "ready" at once. This is worse than D's note that a
  probe "can reach another worker's vanilla". When vanilla then fails to
  bind, it exits, but the body is already running against the impostor, and
  the check at `runner.py:223` only catches an exit that has already been
  reaped. Mutation R5 (swapping that check below `if answer`) **survives**, so
  even that partial guard is untested.
- **Impact**: a Candidate Scenario that runs against another worker's
  Reference yields a false `match`, and `instance.startup` (G4) reads
  milliseconds. No test would fail. Candidates for the impostor: another
  worker's Instance, an orphan from a SIGKILLed harness (Next item 5), or
  any other process.
- **Fix, test first** (in `tests/runner/`): *"`running()` does not yield an
  Instance whose process group does not own the listening socket"*. Start an
  asyncio server on port P, launch `fake_server.py P --never-listen` with
  `ready=accepts_tcp`, and expect `RunnerError` (`not ready … within`, or a
  specific "another process listens on P"). Then make `_ready_ns` require
  that the listener is owned by the process group: map the LISTEN entry for
  host:port in `/proc/net/tcp` to its inode, and look for `socket:[inode]`
  under `/proc/<pid>/fd` for every pid whose pgid is `instance.pid`. This
  check is server-agnostic, which ADR-0004 requires, and stronger than Next
  item 3 (a distinct 127/8 host per Instance). Do both. Also add the R5
  test: *"a probe that answers True after the process exited is not
  ready"*.

### H2 (high). Received stamps are take time, not arrival time

- **Location**: `src/mscts/net.py:167-180` (`_read` stamps after
  `StreamReader.read` returns) and `net.py:147`. The docs are
  `docs/PLAN.md` ("stamped when the socket read that completed the frame
  returned (frames that arrive together share that time, however late they
  are taken)") and the `Connection` docstring, `net.py:54-62`.
- **Evidence**: a fake server writes `status_response` at once, and the
  client sends `intention` and `status_request`, sleeps 300 ms, then calls
  `recv`:

  ```
  $ .venv/bin/python -W error scratchpad/probe_net.py
  P14 status_request -> status_response rtt from the Transcript: 300.8 ms; the
  server wrote it 0.1 ms after the request (stamp is 300.7 ms after the server's write)
  ```

  asyncio moves bytes from the socket into the `StreamReader` buffer in
  `data_received`, whether or not anyone is reading. `_read` stamps when the
  Bot's `read()` call returns, which is whenever the Bot gets round to it. The
  same happens past each 64 KiB `_READ_SIZE` chunk of a burst (e.g.
  `update_tags` ≈ 59 KB plus 32 `registry_data`). The test
  `tests/net/test_connection.py:336`
  (`test_recv_takes_two_frames_of_one_write_in_order_both_stamped_on_arrival`)
  only proves that frames of one read share a stamp, and every test calls
  `recv` before the data arrives. Mutations N5/N6 are killed, so the
  *read-time* policy is pinned, but the *arrival-time* intent is not.
- **Impact**: every Measurement derived from Transcript timestamps (ADR-0001:
  "timing is measured client-side from Transcript timestamps") is inflated
  by however long the Scenario spends between `send` and `recv`. Examples
  are a Control command, a span Mark, or another Bot's work (M7 multi-Bot
  load). A Comparison scoped to windows between Marks (PLAN open question)
  would put packets in the wrong window. `Bot.status`/`ping` are unaffected
  today only because they call `recv` right after `send`.
- **Fix, test first** (`tests/net/test_connection.py`): *"a frame that
  arrives while no `recv` is pending is stamped when it arrived"*. The server
  writes a frame and returns `before`, the client sleeps 200 ms and then calls
  `recv`, and the test asserts `event.t_ns - (before - start_ns) < 20 ms`
  (today: ≈200 ms). Then stamp at the protocol layer: a `Protocol` whose
  `data_received` splits frames with the length prefix and queues
  `(arrival_ns, frame)`. Splitting never depends on compression, so
  decompression and decoding stay at take time, in the current State and
  threshold. The join brief's background reader should be built on this, not
  alongside it. Update the PLAN wording to "stamped when its last byte
  arrived".

### H3 (high). A Candidate's undecodable packet is not recorded, and no Verdict covers it

- **Location**: `src/mscts/net.py:131-148` ("CodecError … Nothing is
  recorded"); `CONTEXT.md` (Verdict `error`); `docs/PLAN.md` Report
  (`compliance = matches / (scenarios − errors)`) and G3.
- **Evidence**: `tests/net/test_connection.py`
  (`test_recv_of_a_packet_that_does_not_fit_its_schema_raises_at_once`)
  asserts `transcript.events == []` after the CodecError. The same holds for
  an unknown packet id (`UnknownPacketError`) and a corrupt frame. The Codec
  is also **stricter than the vanilla client** in several places, verified
  by disassembly: `AbstractByteBuf.readBoolean` is `readByte() != 0`, so vanilla
  reads `0x02` as true where we raise. `Utf8String.read` uses
  `ByteBuf.toString(UTF_8)`, which ends in Netty's `ByteBufUtil.decodeString`
  → `new String(byte[], int, int, Charset)`. That constructor always
  replaces malformed UTF-8 (JDK contract) where we raise.
  `CompressionDecoder.inflate` inflates exactly the declared length, so a
  stream longer than declared is truncated, not rejected. So a Candidate
  quirk that the vanilla client tolerates also surfaces as an exception.
- **Impact**: the M2 Run has no defined outcome for a Candidate-side
  `CodecError`, `ProtocolError`, `ConnectionClosedError` or `TimeoutError`
  when the Reference completed the same Scenario. If it becomes `error`,
  the Candidate is dropped from the denominator and scores better than if
  it had sent a merely wrong value. A `mismatch` would still have no
  Divergence to show, because the offending bytes are not in the
  Transcript.
- **Fix, test first**: (a) in `tests/net/test_connection.py`: *"a frame
  that fails strict decoding is recorded (raw payload, `fields=None` and
  the error) before `recv` raises CodecError"*. This needs a PLAN change: a
  `decode_error: str | None` on `Packet`, or an Event kind for undecodable
  frames, with a synthetic name like `unknown:play:0x2a` for unknown ids.
  (b) For the M2 Run brief: *"a Candidate whose status_response carries one
  trailing byte gets Verdict `mismatch`, with a Divergence at that packet
  showing both payloads"*. Also update CONTEXT: a failure caused by the
  Candidate is `mismatch`, and `error` stays for the harness and the
  Reference. Record in PLAN that the Codec is deliberately stricter than the
  vanilla client and list the three known cases.

### MD1 (medium). VarInt/VarLong decoding returns out-of-range values

- **Location**: `src/mscts/codec/wire.py:125-138` and `:140-153`.
- **Evidence**:

  ```
  Reader.var_int(ff ff ff ff 7f): -> 30064771071
  Reader.var_int(80 80 80 80 10): -> 4294967296
  Reader.var_long(ff*9 7f): -> 1162144876643701751807
    ... and re-encoding that value: RAISES WireError: VarInt 30064771071 out of range
  ```

  Vanilla's `VarInt.read` (26.3, `javap -c`) does
  `out |= (b & 127) << (n++ * 7)` with a 32-bit `ishl`, so the high bits of
  the 5th byte fall off and `ff ff ff ff 7f` reads as −1. `VarLong` does the
  same in 64 bits. Decoding accepts values that encoding rejects, and no Java
  server can represent them.
- **Impact**: a Candidate that sends a non-canonical 5th byte (which the
  vanilla client reads as −1) produces a false `field` Divergence
  (30064771071 vs −1). As a packet id, it produces an UnknownPacketError
  (see H3).
- **Fix, test first** (`tests/codec/test_wire.py`): *"a 5-byte VarInt keeps
  only 32 bits, as vanilla does: `ffffffff7f` → −1, `8080808010` → 0"*, and
  the same for a 10-byte VarLong (`ff*9 7f` → −1). Implement by masking with
  `_INT_MASK`/`_LONG_MASK` before the sign step. Rejecting the input is the
  alternative, but that makes a quirk the vanilla client accepts into an
  error (H3).

### MD2 (medium). `send` records a packet that never left, and raises the wrong error

- **Location**: `src/mscts/net.py:106-129`. PLAN: "ConnectionClosedError if
  the connection was lost … neither writes nor records".
- **Evidence**: a plain-socket server resets (SO_LINGER 0) right after
  accept, and the client blocks for 50 ms, so the event loop has not
  processed the RST, then sends:

  ```
  P18 send after an unnoticed RST raised ConnectionResetError: Connection lost; the
  Transcript holds ['minecraft:intention']; state is now status
  ```

  `transport.is_closing()` (`net.py:121`) only knows what the loop has
  already processed. The write fails in the kernel, `drain()` (`net.py:129`)
  raises, but the Event is already recorded and the State has already
  advanced. The existing test (`test_connection.py:203`) sleeps inside the
  loop, so it only covers the case the guard already sees. Mutation N13
  (`await self._writer.drain()` → `pass`) also survives: no test exercises
  backpressure.
- **Impact**: a phantom serverbound Event appears whenever a server
  disconnects a Bot while the loop is busy, which is likely under the
  milestone M7 load or during a large decode. Comparison takes clientbound packets
  only, so Verdicts are safe, but span Measurements and "the Bot sent X"
  assertions are not. The error type also escapes the documented contract.
- **Fix, test first**: *"a send whose write fails records nothing, leaves
  the State, and raises ConnectionClosedError"*, reproduced as above with a
  blocking `time.sleep` after the RST. Then stamp, write and `drain()`
  first, and record and advance the State only after `drain()` returns,
  converting `ConnectionError` to `ConnectionClosedError`. (The stamp stays
  "immediately before the write".)

### MD3 (medium). `Packet` is frozen but unhashable, and its fields are mutable

- **Location**: `src/mscts/codec/packets.py:35-53`, `:196-209`.
- **Evidence**:

  ```
  hash(packet): RAISES TypeError: unhashable type: 'dict'
  packet.fields['json_response'] = 'tampered': -> {'json_response': 'tampered'}
  ```

- **Impact**: J is building `compare.py` now. Anything that hashes Packets
  (a `set`, a `dict` key, `difflib.SequenceMatcher`, which hashes its
  elements) raises TypeError. Worse, a Mask or canonicalization applied in
  place silently rewrites the recorded Transcript. A Reference Transcript
  can take part in more than one Comparison (for example a Self-check of
  R1 against R2, and then R1 against the Candidate), so the second one would
  see data the first has already masked.
- **Fix, test first**: *"a decoded Packet is hashable and its fields cannot
  be assigned"* (`hash(p)`, and `pytest.raises(TypeError)` on
  `p.fields["x"] = 1`, nested included). Decode into `MappingProxyType`
  holding tuples, which resolves the PLAN open question, or have J's
  Comparison work on copies and pin that with a test. Tell J before its
  first commit lands.

### MD4 (medium). `FrameDecoder.feed` loses frames and can silently misdecode

- **Location**: `src/mscts/codec/framing.py:69-79`.
- **Evidence**:

  ```
  feed raised WireError('frame length VarInt longer than 3 bytes'); buffered now 4
    (the good frame was taken out and lost)
  feed() of login_compression + compressed frame in one chunk returns 2 frames:
      038002 ... 3 bytes
      41789cd34aa61000002f7818 ... 13 bytes
    the Codec reads the second as packet id: -> 65
    ... which is play clientbound: -> 'minecraft:player_abilities'
  ```

  `feed` decodes every frame of a chunk with the threshold in effect when it
  was called. So the compressed frame right behind `login_compression` comes
  back as its raw `data-length ‖ zlib` body, and its data-length (0x41) is
  then decoded as a valid play packet id: a **silent** misdecode, not an error.
- **Blast radius**: none today. `grep` finds no caller outside
  `tests/codec/test_framing.py`: `Connection` and the test fakes use
  `next_frame`. But `feed` is the obvious API for the join brief's
  compression work.
- **Fix, test first**: delete `feed` and move its tests to
  `extend`/`next_frame`. The failing test to write if it is kept instead:
  *"feed of login_compression plus a compressed frame raises or returns the
  decompressed data"*.

### MD5 (medium). A negative compression threshold is not "off"

- **Location**: `src/mscts/codec/framing.py:13-31`, `:112-131`.
- **Evidence**: vanilla `Connection.setupCompression` (26.3, `javap -c`)
  starts with `iload_1; iflt` and removes the compress/decompress handlers
  when `threshold < 0`. `ServerLoginPacketListenerImpl` only sends
  `login_compression` when `getCompressionThreshold() >= 0`. Here:

  ```
  FrameDecoder(threshold=-1) given an uncompressed frame: RAISES WireError: frame payload is not valid zlib data
  encode_frame(b'\x01hi', threshold=-1): -> b'\x0c\x03x\x9cc...'   (compressed)
  ```

  Mutation F8 (treat `< 0` as off) **survives**: nothing pins either
  behaviour.
- **Impact**: a Candidate that sends `login_compression(-1)` to mean "off"
  breaks the join with a CodecError on its next frame (H3 again).
- **Fix, test first** (join brief): *"login_compression with a negative
  threshold leaves both directions uncompressed"*. Map `< 0` to `None` in
  the one place that applies the packet.

### MD6 (medium). `scripts/mutate.py` counts "no tests ran" as a kill

- **Location**: `scripts/mutate.py:106-112` (`verdict`).
- **Evidence**: a no-op mutation, run against a path that does not exist:

  ```
  $ python3 scripts/mutate.py src/mscts/codec/wire.py "_VAR_INT_MAX_BYTES = 5" "_VAR_INT_MAX_BYTES = 5" -- tests/codec/test_wire_typo.py -q
  ERROR: file or directory not found: tests/codec/test_wire_typo.py
  KILLED (pytest exit code 4)
  ```

  pytest's exit codes 2 (interrupted), 3 (internal error), 4 (usage error)
  and 5 (no tests collected) all count as `KILLED`, and so does a mutation
  that breaks an import.
- **Impact**: every worker's "proved it bites" evidence (red-green step 2)
  can be vacuous, for example after a typo in `-k` or a path.
- **Fix, test first** (`tests/tooling/test_mutate.py`): *"verdict(4) and
  verdict(5) are errors (exit 2), not kills"*. Treat only exit 1 and a
  timeout as killed. Also print the collected test count, so a report can
  quote it.

### MD7 (medium). Missing boundary tests (surviving mutations)

Each item below is a mutation that the whole unit tier did not kill. The
exact replacement is given as old → new.

| Id | File | Mutation (old → new) | Why it matters | Test to write first |
| --- | --- | --- | --- | --- |
| W7 | `codec/wire.py:163` | `if byte_length < 0 or byte_length > max_bytes:` → `if byte_length > max_bytes:` | Without the guard, a negative length moves the Reader's offset **backwards** and returns `""`, so later fields re-read old bytes | *String with a negative VarInt length (`ffffffff0f`) raises WireError* |
| W10 | `codec/wire.py:19` | `_NON_BMP_THRESHOLD = 0xFFFF` → `_NON_BMP_THRESHOLD = 0x10FFFF` | UTF-16 counting of non-BMP scalars is untested. The only test is masked by the redundant 3n-byte check | *Writer and Reader reject two U+1F600 (4 code units, 8 bytes) at max_length 3* |
| F5 | `codec/framing.py:118` | `if data_length == 0:` → `if data_length <= 0:` | A negative data-length would silently return compressed bytes as data | *A compressed frame with data-length −1 raises WireError* |
| F6 | `codec/framing.py:125` | `if len(decompressed) != data_length:` → `if len(decompressed) < data_length:` | "Declared shorter than actual" is not pinned (vanilla truncates, we reject: decide, see H3) | *Declared 200, zlib of 300 bytes: raises (or truncates, if that is chosen)* |
| F8 | `codec/framing.py:113` | `if self.compression_threshold is None:\n            return body` → `… is None or self.compression_threshold < 0:` | See MD5 | See MD5 |
| R5 | `runner.py:223-226` | the `returncode` check moved below `if answer:` | See H1 | *A probe answering True after the process exited is not ready* |
| R9 | `runner.py:201` | `process.stdin.close()` (in `_ask_to_stop`) → `pass` | A server that stops on console EOF but ignores the line is never stopped at the stdin step | *fake_server `--stop-on-eof --ignore-stop`: stopped by stdin* |
| N13 | `net.py:129` | `await self._writer.drain()` → `pass` | No backpressure: writes to a server that stopped reading pile up unbounded | *send to a peer that never reads blocks (bounded by the Bot timeout) once the buffer is full* |
| P5 | `codec/packets.py:233` | `… or isinstance(protocol_id, bool):` removed | A `true` id in a packet report would load as id 1 | *A packet report with `"protocol_id": true` raises CodecError* |
| P6 | `codec/packets.py:225` | `if not isinstance(value, dict):` → `if False:` | A malformed report raises AttributeError, not CodecError | *A packet report that is a JSON list raises CodecError* |
| G3 | `codec/regen.py:58` | `cwd=output,` → `cwd=None,` | The rule "run the generator outside the repo" is untested. With `cwd=None` it unpacks `libraries/` into the caller's cwd | *The generator runs with cwd = the output dir* (stub java writes `$PWD`) |
| R11 | `runner.py:239` | `log.seek(max(0, size - _LOG_TAIL_BYTES))` → `log.seek(0)` | The 64 KiB bound on reading a console log is untested. A chatty server's multi-MB log would be read in full for every RunnerError | *The log tail of a 10 MB console reads at most 64 KiB* (spy on `read`) |

Equivalent survivors (no test can kill them, so each is a candidate for
deletion or a comment):

- W8 (`max_length * _BYTES_PER_CODE_UNIT` → `* 4`, `wire.py:162`) and W9
  (`if len(encoded) > max_length * _BYTES_PER_CODE_UNIT:` → `if False:`,
  `wire.py:77`). Valid UTF-8 never takes more than 3 bytes per UTF-16 code
  unit, so these byte bounds are implied by the code-unit check. They only
  change the error message and when the check fires. W9 is dead code, and
  worse, it hides W10.
- F3 (`if result > _FRAME_LENGTH_MAX_VALUE:` → `if False:`,
  `framing.py:48`) is unreachable, because 3 × 7 bits = 2 097 151 (already
  noted by worker A).
- W14 (`0x01 if value else 0x00` → `0x01 if value is True else 0x00`) is
  equivalent for bools. The real gap is L4.
- N8 (idempotence guard in `close`), N14 (`max` of monotonic stamps) and N15
  (`_CLOSE_TIMEOUT_S` 1.0 → 30.0) are equivalent because asyncio's
  `close()`/`wait_closed()` are themselves idempotent and the monotonic
  clock never goes backwards. The 1 s abort grace is only checked with a
  patched value.
- R13 (no stdin close before SIGTERM, `runner.py:185-186`) makes no
  difference for any server we know: none stops on console EOF, and asyncio
  closes the pipe when the process exits. PLAN does not specify this step.

### MD8 (medium). A double cancellation leaves an unclosed subprocess transport, hidden by the test

- **Location**: `src/mscts/runner.py:156-163` (the `except BaseException`
  branch of `_stop`); the test is
  `tests/runner/test_running_cleanup.py`
  (`test_cancelling_again_during_the_stop_kills_the_process_at_once`).
- **Evidence**: `scratchpad/probe_cleanup.py` runs the same scenario as that
  test (a fake server ignoring stop and SIGTERM, cancelled twice) but lets
  `asyncio.run` return at once, as a real harness does after a second
  Ctrl-C:

  ```
  $ .venv/bin/python -X dev scratchpad/probe_cleanup.py double
  warnings: ['ResourceWarning: unclosed transport <_UnixSubprocessTransport pid=1814 running
             stdin=<_UnixWritePipeTransport closed fd=8 closed>>']
  pid 1814 state right after asyncio.run returned: gone
  $ .venv/bin/python -X dev scratchpad/probe_cleanup.py single
  warnings: []
  ```

  The branch SIGKILLs and re-raises without letting the loop see the exit.
  The unit test hides this because it then waits
  `eventually(lambda: not is_alive(pid))` inside the same loop, which gives
  asyncio time to reap the process and close the transport. There is no
  process leak: the process is gone.
- **Impact**: under `filterwarnings = error`, a future test (or Run
  teardown) that cancels twice and returns promptly will fail a *later*,
  unrelated test when the transport is garbage-collected. This is the same
  misattribution trap as the leaked-socket Known trap.
- **Fix, test first**: *"a second cancellation during the stop leaves no
  unclosed transport even when the event loop ends at once"*. It is a sync
  test: `asyncio.run(scenario)` under
  `warnings.catch_warnings(record=True)`, then `gc.collect()`, then assert
  no ResourceWarning. Then, after the SIGKILL in that branch, await the exit
  briefly: `await asyncio.wait_for(asyncio.shield(process.wait()), 1)`
  under `contextlib.suppress(BaseException)`, before `raise`.

### Low

- **L1. A lone surrogate escapes as UnicodeEncodeError, not CodecError.**
  `codec/wire.py:76`. `Codec.encode(intention, server_address="\ud800")`
  raises `builtins.UnicodeEncodeError`, and `Connection.send` inherits it,
  breaking "CodecError if the fields do not fit". Vanilla's
  `ByteBufUtil.writeUtf8` writes `?` instead. Test: *encode of a String field
  holding a lone surrogate raises CodecError*.
- **L2. Zero-length frames are accepted.** `framing.py:96-105`. Vanilla's
  `Varint21FrameDecoder` throws "Frame length cannot be zero" (26.3,
  `javap -c`). Here, `next_frame(b"\x00")` returns `b""`
  (`test_framing.py:149` even asserts it), `Codec.decode` then fails with
  the misleading "packet id: VarInt truncated", and `encode_frame(b"")`
  produces a frame vanilla rejects. Test: *a zero frame length raises
  WireError, and encode_frame(b"") raises*.
- **L3. `encode_frame` does not enforce the protocol limits.**
  `framing.py:13-31`. `encode_frame(2 MiB)` writes the 4-byte prefix
  `80808001`, which our own decoder rejects ("longer than 3 bytes").
  Vanilla's encoder also caps uncompressed data at 8 388 608. Test:
  *encode_frame of 2 097 152 bytes raises WireError*.
- **L4. The Writer does not type-check Bool or UUID.** `wire.py:102-110`.
  `Writer.bool_(value=2)` writes `01`, `Writer.bool_(value="")` writes `00`
  and `Writer.uuid("x")` raises AttributeError. Nothing reaches these yet,
  because there is no `BOOL`/`UUID` WireType in `schema.py`. When one is
  added (M4 `hello` has a UUID), the first test is *BOOL rejects 1 and "",
  UUID rejects a str, each with WireError*, the mirror of "ints reject
  bool".
- **L5. `String(max_length)` does not type-check.** `schema.py:99-107`.
  `String(True)` and `String(2.5)` are accepted. Test: *String(True) raises
  SchemaError*.
- **L6. `instance.startup` includes the successful probe's own round
  trip.** `runner.py:226`. `ready_ns` is taken when `status_probe` returns,
  so it includes connect + handshake + status (about 20 ms warm and 70–95 ms
  for a first connection, per the domain research) plus up to 20 ms of
  polling. A Candidate with a slow status handler looks slower to start.
  Document the definition in PLAN `Instance`, or record the probe's start
  time as well.
- **L7. `regen` runs the generator with the harness environment.**
  `codec/regen.py:56-63`: no `env=`, no `LAUNCH_ENV`, no `NO_NETWORK`, so
  `JAVA_TOOL_OPTIONS` (set in this container) reaches it. The output is
  byte-identical anyway, which the reference test verifies, so this is only
  host dependence. Also note G3 in MD7.
- **L8. The state switch follows the Bot's send, not the vanilla client's
  receipt.** `net.py:195-207`. The vanilla client switches its *inbound*
  State when it handles `login_finished`/`finish_configuration`/
  `start_configuration`, and its outbound State after sending the ack. This
  is from memory of the client code, which is not in the server jar, so it
  is **unverified** here. The two models agree only while the Bot takes
  nothing between the transition packet and its ack. The join brief should
  pin the rule with a fake server that pipelines a configuration packet
  right behind `login_finished`.
- **L9. `_parse_packet_report` raises ValueError, not CodecError, for an
  unknown State key.** `packets.py:213-221` (`State("bogus")`), contrary to
  its docstring.
- **L10. Duplicate helpers.** `tests/runner/conftest.py:94-126` duplicates
  `tests/support/leak_guard.py`, and `tests/net/fakes.py:179` duplicates
  `runner.free_port`. `test_status_probe.py:29`
  (`..._false_when_nothing_listens`) relies on a free port staying free:
  another worker's vanilla on that port turns it red (rare, but it will
  happen).
- **L11. Bot names are not unique.** Nothing stops two Bots in one
  Transcript from sharing a name, and Comparison is per Bot. Make
  `ScenarioContext.bot()` refuse a duplicate when it is built (M2).

### Drift

| Where | Code | Docs | Which side is right |
| --- | --- | --- | --- |
| `transcript.py` | no `to_jsonl`/`from_jsonl`, no Mark writer | PLAN module table and `Transcript` sketch list JSON-lines (de)serialization | Docs: it is still to be built. When it is, the first test must round-trip `bool` vs `int`, `bytes`, `UUID` and ints > 2⁵³ |
| `net.py` `recv` on RST | raises `ConnectionResetError` (pinned by `test_connection.py:203`) | PLAN: "ConnectionClosedError when the server closes" | Code, because both are `ConnectionError`. Say "ConnectionError (ConnectionClosedError on FIN, ConnectionResetError on RST)" in PLAN |
| `net.py` `send` | records then raises `ConnectionResetError` (MD2) | "ConnectionClosedError … neither writes nor records" | Docs; fix the code |
| `net.py` stamps | take time (H2) | "frames that arrive together share that time, however late they are taken"; test name "stamped on arrival" | Docs (the intent); fix the code |
| CONTEXT "Transcript" | undecodable and untaken frames are absent (H3, PLAN open question) | "every Packet each Bot sent and received" | Code should record undecodable frames; CONTEXT should say "every Packet each Bot took" until the background reader lands |
| CONTEXT "Verdict" | n/a | `error` = harness or Reference failure; nothing covers a Candidate failure | Docs: add it (H3) |
| `runner.running` | `ready_timeout`, `stop_timeout` (seconds) | the `timeout_s` convention (red-green Known traps) | Matches PLAN; rename to `ready_timeout_s`/`stop_timeout_s` with the next runner change |
| PLAN `Bot` | `join`, `expect`, `send`, `command` absent | listed | Expected (M4/M5), not drift |
| ADR-0004 | tests inject `accepts_tcp` | "A TCP connect is not readiness, not even as a stand-in" | Consistent: PLAN allows injected probes in unit tests, and every reference-tier boot uses `status_probe` |

## Checked and found sound

The next audit can skip these unless the code changes:

- **Encode strictness.** `Schema.write` needs exactly the declared names
  (missing and unexpected are reported together, nested paths are named),
  ints reject bool and float, `String` rejects non-str, and VarInt, VarLong,
  UShort and Long reject out-of-range values on both sides (W1–W3, S1–S8
  killed).
- **Decode strictness.** `Codec.decode` consumes the payload exactly
  (`expect_end`, P3 killed). Errors are prefixed with the field path, and
  unknown ids raise `UnknownPacketError`. A schema for a packet the Target
  lacks is refused at construction. Duplicate ids are refused. All 260
  `packets.json` entries round-trip name ↔ id.
- **Framing** matches vanilla 26.3 in everything that matters to a client
  (verified with `javap -c`):
  - the frame length is at most 3 bytes ("length wider than 21-bit");
  - compression applies when `len >= threshold` (`CompressionEncoder`);
  - data-length 0 means uncompressed, with no size check;
  - zlib trailing bytes are ignored, as vanilla's fixed-size `Inflater`
    call ignores them;
  - taking frames one at a time lets a new threshold apply from the very
    next frame of the same chunk.

  Vanilla's *server* also rejects a compressed frame whose data-length is
  below the threshold or above 8 388 608 (`validateDecompressed`, set to
  `true` in `ServerLoginPacketListenerImpl`). That is the answer to Next
  item 2's "verify vanilla's rule" for the server side. The client passes
  its own flag, and its code is not in the server jar.
- **Connection ordering.** Per Bot, clientbound Events stay in wire order.
  Frames are taken in order, stamps never decrease, and `insort_right` keeps
  ties in recording order (T3/T5 killed). A `recv` timeout loses no bytes:
  a cancelled `StreamReader.read` leaves its data in the buffer, and
  `_read` has no await after the read. Frames are never duplicated or
  reordered.
- **State machine.** Intents 1/2/3, `login_acknowledged` and
  `finish_configuration` work (N1, N3 killed). An unknown intent writes and
  records nothing. A packet of a later State is refused.
- **Bot.** Every operation, connect included, is bounded (B11/B12 killed).
  The handshake is sent once, the answers are checked, and the answer is
  recorded before a ProtocolError.
- **status_probe.** It returns False for refused, reset, closed and timeout;
  it raises for another protocol, a missing or bool protocol, or a garbled
  answer; and it closes on every path, cancellation included (B5–B9
  killed). Loading a Codec costs 0.37 ms per probe, which is negligible.
- **Runner cleanup.**
  - Its own session and process group, exact env, cwd, and console to a
    file (R1/R2 killed).
  - The escalation stdin → SIGTERM → SIGKILL, each after `stop_timeout`,
    with the level logged (R8, R16 killed).
  - The group is SIGKILLed after a graceful exit, so the fork child dies
    (R6 killed).
  - A second cancellation kills at once (R7 killed).
  - The probe's own TimeoutError is not taken for the deadline (R3 killed).
  - A launch failure gives `RunnerError` with `exit_code=None`.
  - A single cancellation followed by an immediate end of the event loop
    leaves no ResourceWarning and no process (`probe_cleanup.py single`). The
    double-cancellation case is MD8.
- **Transcript.** It rejects times before the start and in the future
  (T1/T2 killed), and equality ignores `start_ns` (T4 killed).
- **Loop binding.** No module-level asyncio object. The session Reference
  fixture yields a plain `Instance`, so nothing loop-bound outlives its loop.
  No task is created without being awaited.
- **Shared state under parallel workers.** Cache writes are atomic renames
  (`vanilla.py:105-110`). regen uses a private `TemporaryDirectory`. The
  shared Reference is only used for status and ping, which change nothing
  (its conftest says so). The shared-Reference fixture's leak guard is
  per-session.
- **Tiers.** `mise run check` is green in about 6.8 s (516 unit tests).
  `mise run test:reference` is green, with 8 passed in 45.3 s (G5 < 90 s holds).
  Vanilla boots took 10.3 s cold and 9.2 s warm, and stopped by stdin in
  1.3 s and 0.4 s. `scripts/strays.py` found nothing left afterwards.

## Mutation log

Each mutation ran as
`python3 scripts/mutate.py --timeout 150 <file> <old> <new> -- -x -q -p no:cacheprovider -m "not reference and not candidate"`
(the whole unit tier), from `scratchpad/mutations.py`. Paths are under
`src/mscts/`. "Killed" means that pytest exited 1 (MD6 says why that
matters). `git status` was clean after the batch.

| Id | File | Old | New | Result |
| --- | --- | --- | --- | --- |
| W1 | `codec/wire.py` | `if not -_INT_SIGN <= value < _INT_SIGN:` | `if not -_INT_SIGN <= value <= _INT_SIGN:` | killed |
| W2 | `codec/wire.py` | `if not -_INT_SIGN <= value < _INT_SIGN:` | `if not -_INT_SIGN - 1 <= value < _INT_SIGN:` | killed |
| W3 | `codec/wire.py` | `if not -_LONG_SIGN <= value < _LONG_SIGN:` | `if not -_LONG_SIGN <= value <= _LONG_SIGN:` | killed |
| W4 | `codec/wire.py` | `for index in range(_VAR_INT_MAX_BYTES):` | `for index in range(_VAR_INT_MAX_BYTES + 1):` | killed |
| W5 | `codec/wire.py` | `for index in range(_VAR_LONG_MAX_BYTES):` | `for index in range(_VAR_LONG_MAX_BYTES + 1):` | killed |
| W6 | `codec/wire.py` | `return result - (1 << 32) if result & _INT_SIGN else result` | `return result` | killed |
| W7 | `codec/wire.py` | `if byte_length < 0 or byte_length > max_bytes:` | `if byte_length > max_bytes:` | **survived** |
| W8 | `codec/wire.py` | `max_bytes = max_length * _BYTES_PER_CODE_UNIT` | `max_bytes = max_length * 4` | **survived** (equivalent) |
| W9 | `codec/wire.py` | `if len(encoded) > max_length * _BYTES_PER_CODE_UNIT:` | `if False:` | **survived** (equivalent) |
| W10 | `codec/wire.py` | `_NON_BMP_THRESHOLD = 0xFFFF` | `_NON_BMP_THRESHOLD = 0x10FFFF` | **survived** |
| W11 | `codec/wire.py` | `if byte == 0x01:` | `if byte != 0x00:` | killed |
| W12 | `codec/wire.py` | `if self.remaining:` (in `expect_end`) | `if self.remaining > 1:` | killed |
| W13 | `codec/wire.py` | `if end > len(self._data):⏎ msg = "uuid truncated"` | `if end > len(self._data) + 1:⏎ msg = "uuid truncated"` | killed |
| W14 | `codec/wire.py` | `self._buffer.append(0x01 if value else 0x00)` | `self._buffer.append(0x01 if value is True else 0x00)` | **survived** (equivalent) |
| F1 | `codec/framing.py` | `if len(data) >= compression_threshold:` | `if len(data) > compression_threshold:` | killed |
| F2 | `codec/framing.py` | `_FRAME_LENGTH_MAX_BYTES = 3` | `_FRAME_LENGTH_MAX_BYTES = 4` | killed |
| F3 | `codec/framing.py` | `if result > _FRAME_LENGTH_MAX_VALUE:` | `if False:` | **survived** (equivalent) |
| F4 | `codec/framing.py` | `if end > len(self._buffer):` | `if end >= len(self._buffer):` | killed |
| F5 | `codec/framing.py` | `if data_length == 0:` | `if data_length <= 0:` | **survived** |
| F6 | `codec/framing.py` | `if len(decompressed) != data_length:` | `if len(decompressed) < data_length:` | **survived** |
| F7 | `codec/framing.py` | `while (frame := self.next_frame()) is not None:` | `if (frame := self.next_frame()) is not None:` | killed |
| F8 | `codec/framing.py` | `if self.compression_threshold is None:⏎ return body` | `if self.compression_threshold is None or self.compression_threshold < 0:⏎ return body` | **survived** |
| S1 | `codec/schema.py` | `if isinstance(value, bool) or not isinstance(value, int):` | `if not isinstance(value, int):` | killed |
| S2 | `codec/schema.py` | `if not 1 <= self.max_length <= _STRING_MAX_LENGTH:` | `if not 0 <= self.max_length <= _STRING_MAX_LENGTH:` | killed |
| S3 | `codec/schema.py` | `if not 1 <= self.max_length <= _STRING_MAX_LENGTH:` | `if not 1 <= self.max_length <= _STRING_MAX_LENGTH + 1:` | killed |
| S4 | `codec/schema.py` | `if not isinstance(value, str):` | `if False:` | killed |
| S5 | `codec/schema.py` | `msg = f"{name}: {exc}"⏎ raise WireError(msg) from exc⏎ return values` | `raise⏎ return values` | killed |
| S6 | `codec/schema.py` | `missing = [name for name, _ in self._fields if name not in given]` | `missing = []` | killed |
| S7 | `codec/schema.py` | `unexpected = sorted(str(name) for name in given if name not in declared)` | `unexpected = []` | killed |
| S8 | `codec/schema.py` | `if not isinstance(value, Mapping):` | `if False:` | killed |
| P1 | `codec/packets.py` | `if other != name:` | `if False:` | killed |
| P2 | `codec/packets.py` | `if (state, direction, name) not in self._ids:` | `if False:` | killed |
| P3 | `codec/packets.py` | `reader.expect_end()` | `pass` | killed |
| P4 | `codec/packets.py` | `payload = data[len(data) - reader.remaining :]` | `payload = data` | killed |
| P5 | `codec/packets.py` | `if not isinstance(protocol_id, int) or isinstance(protocol_id, bool):` | `if not isinstance(protocol_id, int):` | **survived** |
| P6 | `codec/packets.py` | `if not isinstance(value, dict):` (in `_json_object`) | `if False:` | **survived** |
| P7 | `codec/packets.py` | `return cls(_parse_packet_report(report), _SCHEMAS.get(minecraft_version))` | `return cls(_parse_packet_report(report), None)` | killed |
| N1 | `net.py` | `3: State.LOGIN}` | `3: State.STATUS}` | killed |
| N2 | `net.py` | `if self._writer.transport.is_closing():` | `if False:` | killed |
| N3 | `net.py` | `self._state = state_after` | `self._state = self._state` | killed |
| N4 | `net.py` | `t_ns = self._transcript.now_ns()⏎ self._writer.write(frame)` | `self._writer.write(frame)⏎ t_ns = self._transcript.now_ns()` | killed |
| N5 | `net.py` | `self._transcript.record(self._bot, packet, t_ns=self._last_read_ns)` | `self._transcript.record(self._bot, packet, t_ns=self._transcript.now_ns())` | killed |
| N6 | `net.py` | `chunk = await self._reader.read(_READ_SIZE)⏎ t_ns = self._transcript.now_ns()` | `t_ns = self._transcript.now_ns()⏎ chunk = await self._reader.read(_READ_SIZE)` | killed |
| N7 | `net.py` | `self._writer.transport.abort()` | `pass` | killed |
| N8 | `net.py` | `if self._closed:⏎ return` | `if False:⏎ return` | **survived** (equivalent) |
| N9 | `net.py` | `if self._frames.buffered:` | `if False:` | killed |
| N10 | `net.py` | `raise CodecError(msg) from exc` | `raise` | killed |
| N11 | `net.py` | `self._check_open()⏎ async with` (recv) | `async with` | killed |
| N12 | `net.py` | `self._check_open()⏎ data =` (send) | `data =` | killed |
| N13 | `net.py` | `await self._writer.drain()` | `pass` | **survived** |
| N14 | `net.py` | `self._frames.extend(chunk)⏎ self._last_read_ns = t_ns` | `… self._last_read_ns = max(t_ns, self._last_read_ns)` | **survived** (equivalent) |
| N15 | `net.py` | `_CLOSE_TIMEOUT_S = 1.0` | `_CLOSE_TIMEOUT_S = 30.0` | **survived** (equivalent) |
| B1 | `bot.py` | `_expect(packet, "minecraft:status_response")` | `pass` | killed |
| B2 | `bot.py` | `if echoed != payload:` | `if False:` | killed |
| B3 | `bot.py` | `if self._connection.state is State.HANDSHAKE:` | `if True:` | killed |
| B4 | `bot.py` | `intent=1,` | `intent=2,` | killed |
| B5 | `bot.py` | `except (ConnectionError, TimeoutError):⏎ return False⏎ try:` | `except TimeoutError:⏎ return False⏎ try:` | killed |
| B6 | `bot.py` | `except (ConnectionError, TimeoutError):⏎ return False⏎ finally:` | `except TimeoutError:⏎ return False⏎ finally:` | killed |
| B7 | `bot.py` | `if isinstance(protocol, bool) or not isinstance(protocol, int):` | `if not isinstance(protocol, int):` | killed |
| B8 | `bot.py` | `if protocol != target.protocol_version:` | `if False:` | killed |
| B9 | `bot.py` | `finally:⏎ await bot.close()` | `finally:⏎ pass` | killed |
| B10 | `bot.py` | `if not isinstance(value, dict):` (in `_json_object`) | `if False:` | killed |
| B11 | `bot.py` | `async with asyncio.timeout(self._timeout_s):` (status) | `async with asyncio.timeout(None):` | killed |
| B12 | `bot.py` | `async with asyncio.timeout(timeout_s):` (connect) | `async with asyncio.timeout(None):` | killed |
| B13 | `bot.py` | `server_address=self._endpoint.host,` | `server_address="localhost",` | killed |
| B14 | `bot.py` | `server_port=self._endpoint.port,` | `server_port=25565,` | killed |
| T1 | `transcript.py` | `if t_ns < 0:` | `if t_ns < -1:` | killed |
| T2 | `transcript.py` | `if t_ns > self.now_ns():` | `if t_ns >= self.now_ns():` | killed |
| T3 | `transcript.py` | `bisect.insort_right(` | `bisect.insort_left(` | killed |
| T4 | `transcript.py` | `default_factory=time.monotonic_ns, compare=False` | `default_factory=time.monotonic_ns, compare=True` | killed |
| T5 | `transcript.py` | `bisect.insort_right(self.events, event, key=_event_time)` | `self.events.append(event)` | killed |
| R1 | `runner.py` | `start_new_session=True,` | `start_new_session=False,` | killed |
| R2 | `runner.py` | `env=dict(plan.env),` | `env=None,` | killed |
| R3 | `runner.py` | `if not readiness.expired():` | `if readiness.expired():` | killed |
| R4 | `runner.py` | `if process.returncode is not None:⏎ return None⏎ if answer:` | `if False:⏎ return None⏎ if answer:` | killed |
| R5 | `runner.py` | `if process.returncode is not None:⏎ return None⏎ if answer:⏎ return time.monotonic_ns()` | `if answer:⏎ return time.monotonic_ns()⏎ if process.returncode is not None:⏎ return None` | **survived** |
| R6 | `runner.py` | `raise⏎ exit_code = await process.wait()  # at once: it has exited` | the same, then `return exit_code` (skips the final group SIGKILL) | killed |
| R7 | `runner.py` | `_signal_group(process, signal.SIGKILL)⏎ raise` | `raise` | killed |
| R8 | `runner.py` | `graceful = how == ("stdin" if plan.stop_stdin is not None else "SIGTERM")` | `graceful = True` | killed |
| R9 | `runner.py` | `process.stdin.close()⏎ await process.wait()` (in `_ask_to_stop`) | `pass⏎ await process.wait()` | **survived** |
| R10 | `runner.py` | `return False⏎ return True` (in `_within`) | `return True⏎ return True` | killed |
| R11 | `runner.py` | `log.seek(max(0, size - _LOG_TAIL_BYTES))` | `log.seek(0)` | **survived** |
| R12 | `runner.py` | `LOG_TAIL_LINES = 40` | `LOG_TAIL_LINES = 41` | killed |
| R13 | `runner.py` | `if process.stdin is not None:⏎ process.stdin.close()⏎ _signal_group(process, signal.SIGTERM)` | `_signal_group(process, signal.SIGTERM)` | **survived** (equivalent) |
| R14 | `runner.py` | `launched_ns = time.monotonic_ns()` | `launched_ns = time.monotonic_ns() + 10_000_000` | killed |
| R15 | `runner.py` | `return time.monotonic_ns()` (in `_ready_ns`) | `return time.monotonic_ns() + 30_000_000` | killed |
| R16 | `runner.py` | `… await _within(stop_timeout, _ask_to_stop(process, stop_stdin)):` | `… await _within(stop_timeout * 2, _ask_to_stop(process, stop_stdin)):` | killed |
| G1 | `codec/regen.py` | `if result.returncode != 0:` | `if False:` | killed |
| G2 | `codec/regen.py` | `if generated != committed:` | `if False:` | killed |
| G3 | `codec/regen.py` | `cwd=output,` | `cwd=None,` | **survived** |

Total: 90 mutations, of which 70 were killed and 20 survived (12 missing
tests and 8 equivalent). `⏎` marks a newline inside a replacement, and
leading indentation is left out here. `scratchpad/mutations.py` passes the
exact, indented strings.

## Proposed order of work

1. Before J's `compare.py` lands: tell J about MD3. Make Packets hashable and
   immutable, or have Comparison copy them.
2. In the M2 Run brief: H3's Verdict rule and the recording of undecodable
   frames. Write the "trailing byte → mismatch" test first.
3. In the join brief:
   - H2: arrival stamping in a protocol layer, which the background reader
     then uses;
   - MD4: delete `feed`;
   - MD5: a negative threshold means off;
   - MD1: VarInt truncation;
   - L4: the BOOL/UUID guards;
   - L8: the state-switch rule;
   - MD2: record after drain.
4. Change Next item 3 into H1: the listener-ownership check plus the 127/8
   host. Include MD8 (the double-cancellation transport) and the R5, R9
   and R11 tests in the same runner brief.
5. A tooling commit for MD6 (`mutate.py` verdicts).
6. The survivors in MD7 and the low items, as each module is next touched.
