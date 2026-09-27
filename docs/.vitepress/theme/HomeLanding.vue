<template>
  <div class="ms-home">
    <section class="ms-hero">
      <div>
        <p class="ms-eyebrow">Minecraft 26.3 · protocol 777</p>
        <h1>Measure how close your server is to <span>vanilla</span>.</h1>
        <p class="ms-intro">
          mscts connects to vanilla Minecraft and to your server as an ordinary
          client. It runs the same script against each, compares every packet
          they send back, and times both. The result lists each difference a
          player could notice.
        </p>
        <div class="ms-actions">
          <a class="ms-button primary" href="/getting-started">Get started</a>
          <a class="ms-button" href="/guide/how-it-works">How it works</a>
          <a class="ms-button" href="https://github.com/ericbstie/mscts">GitHub</a>
        </div>
      </div>
      <div class="ms-term" aria-label="A Report from mscts run, vanilla against Pumpkin">
        <div class="ms-term-bar"><i></i><i></i><i></i></div>
<pre v-pre><span class="prompt">$</span> mscts run --candidate pumpkin
<span class="muted">starting vanilla and pumpkin ...
running status/basic (1 of 5) ...
...</span>

<span class="head">mscts Report</span>
  Reference    vanilla (its status says version "26.3")
  Candidate    pumpkin (its status says version "26.3")
  Target       Minecraft 26.3 (protocol 777)
  Repetitions  5 of each scenario

2 scenarios: 2 different on the wire only. No difference
a player would notice was found.

<span class="head">Wire-only differences</span>
  Server list ping (status)
    status_response: 4 values differ on the wire, e.g.
      - json_response.description: vanilla sends "mscts",
        pumpkin sends {"text": "mscts"}
      - json_response.favicon: vanilla leaves it out,
        pumpkin sends null
      <span class="muted">...</span>

<span class="head">Timings (ms)</span>
  measurement       vanilla median  pumpkin median  n
  status.rtt                  2.03            0.33  5
  instance.startup          15,499              31  1</pre>
      </div>
    </section>

    <section class="ms-section">
      <h2>A Run plays the same Scenario against both servers</h2>
      <p>
        Vanilla is the Reference. Your server is the Candidate. mscts never
        reads either server's code. It only sees what goes over the wire, so
        it works the same for a server written in Rust, Java or anything else.
      </p>
      <div class="ms-steps">
        <div class="ms-card">
          <h3>Install</h3>
          <p>
            <code>mscts adapter install</code> downloads a server build that the
            Registry pins by checksum, or copies one you pass with
            <code>--from</code>.
          </p>
        </div>
        <div class="ms-card">
          <h3>Launch</h3>
          <p>
            An Adapter writes each server's native config from one ServerSpec.
            Both start offline, each on its own loopback address.
          </p>
        </div>
        <div class="ms-card">
          <h3>Play</h3>
          <p>
            Bots speak the protocol the way the vanilla client does and record
            every packet, with its arrival time, in a Transcript.
          </p>
        </div>
        <div class="ms-card">
          <h3>Compare</h3>
          <p>
            mscts diffs the two Transcripts field by field. Any difference from
            vanilla is a Divergence, reported with the packet, the field path
            and both values.
          </p>
        </div>
      </div>
    </section>

    <section class="ms-section">
      <h2>What a player can see, and what only the wire can</h2>
      <p>
        Two servers can send different bytes that the vanilla client decodes to
        the same value. mscts checks each difference against how the client
        reads it and files it in one of two groups. Only observable differences
        count toward compliance.
      </p>
      <div class="ms-split">
        <div class="ms-card">
          <span class="ms-tag observable">observable</span>
          <p>
            The vanilla client reads the Candidate's value differently from
            vanilla's, so a player could notice it. A missing packet, a
            different player limit in the server list, or a server that closes
            the connection all land here.
          </p>
        </div>
        <div class="ms-card">
          <span class="ms-tag wire">wire-only</span>
          <p>
            The bytes differ but decode to the same thing. Vanilla 26.3 sends
            its server description as the string <code>"mscts"</code>, and
            Pumpkin sends <code>{"text": "mscts"}</code>. The client shows both
            as the same text.
          </p>
        </div>
      </div>
    </section>

    <section class="ms-section">
      <h2>Rules mscts follows</h2>
      <ul class="ms-list">
        <li>
          <b>Vanilla is always right.</b> There is no list of accepted
          deviations. If the Candidate differs, the Report says so.
        </li>
        <li>
          <b>Every Scenario passes a Self-check.</b> It runs vanilla against
          vanilla and must match in 20 runs out of 20.
        </li>
        <li>
          <b>One Adapter per server.</b> Supporting a new server means one small
          module that turns a ServerSpec into a launch command.
        </li>
        <li>
          <b>Installs are explicit.</b> Nothing downloads during a Run. Every
          download names its URL and checks a pinned hash.
        </li>
        <li>
          <b>Timings are repeated.</b> Each measurement reports its median
          and p95 over repeated runs, next to startup time.
        </li>
        <li>
          <b>Servers stay local.</b> Each Instance runs in offline mode, bound
          to 127.0.0.0/8, with outbound network access turned off.
        </li>
      </ul>
    </section>

    <section class="ms-section">
      <h2>What works today</h2>
      <p>
        mscts targets Minecraft 26.3 only. Today it plays the server list
        Scenarios against vanilla and Pumpkin and prints a text Report. Bots
        can join the game; gameplay Scenarios are next.
      </p>
      <div class="ms-actions ms-cta">
        <a class="ms-button" href="/status">See the project status</a>
      </div>
    </section>
  </div>
</template>
