<template>
  <div class="ms-home">
    <section class="ms-hero">
      <div>
        <h1>Minecraft Server Compliancy Test Suite — mscts</h1>
        <p class="ms-intro">
          mscts is a test suite to objectively measure how closely a custom
          Minecraft server mimics the behavior of a vanilla Minecraft server.
        </p>
        <div class="ms-actions">
          <a class="ms-button primary" :href="withBase('/getting-started')">Get started</a>
          <a class="ms-button" :href="withBase('/guide/how-it-works')">How it works</a>
          <a class="ms-button" href="https://github.com/ericbstie/mscts">GitHub</a>
        </div>
      </div>
      <div class="ms-term" aria-label="A Report from mscts run, vanilla against Pumpkin">
        <div class="ms-term-bar"><i></i><i></i><i></i></div>
<pre v-pre><span class="prompt">$</span> mscts run --candidate pumpkin
Running tests against pumpkin
Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)
<span class="ms-pass">✓</span> status/basic/status_response.description Server list description (network traffic only)
<span class="ms-pass">✓</span> status/basic/status_response.description.text Server list description text
<span class="ms-pass">✓</span> status/basic/status_response.enforceSecureChat Unused secure chat flag (network traffic only)
<span class="ms-pass">✓</span> status/basic/status_response.favicon Server list icon (network traffic only)
<span class="ms-pass">✓</span> status/basic/status_response.players.max Player limit
<span class="ms-pass">✓</span> status/basic/status_response.players.online Online players
<span class="ms-pass">✓</span> status/basic/status_response.players.sample Server list player sample (network traffic only)
<span class="ms-pass">✓</span> status/basic/status_response.version.name Server version name
<span class="ms-pass">✓</span> status/basic/status_response.version.protocol Protocol version
<span class="ms-pass">✓</span> status/ping/status:pong_response.timestamp Server list ping response
<span class="ms-pass">✓</span> status/ping/status_response.description Server list description (network traffic only)
<span class="ms-pass">✓</span> status/ping/status_response.description.text Server list description text
<span class="ms-pass">✓</span> status/ping/status_response.enforceSecureChat Unused secure chat flag (network traffic only)
<span class="ms-pass">✓</span> status/ping/status_response.favicon Server list icon (network traffic only)
<span class="ms-pass">✓</span> status/ping/status_response.players.max Player limit
<span class="ms-pass">✓</span> status/ping/status_response.players.online Online players
<span class="ms-pass">✓</span> status/ping/status_response.players.sample Server list player sample (network traffic only)
<span class="ms-pass">✓</span> status/ping/status_response.version.name Server version name
<span class="ms-pass">✓</span> status/ping/status_response.version.protocol Protocol version
19 passed, 0 failed
Score: 100% (19 of 19 test cases pass)
Took 26.1 s</pre>
      </div>
    </section>

    <section class="ms-section">
      <h2>Why use this tool?</h2>
      <p>
        The official vanilla Minecraft server implementation includes a lot of
        features and gameplay quirks that a modified Minecraft server most
        likely wants to uphold. mscts gives developers a simpler way to check exactly which
        features and quirks are kept.
      </p>
      <p>
        As a developer, you can use the results as a benchmark to work
        towards, much like
        <a href="https://github.com/tc39/test262">Test262</a> (the official
        ECMAScript conformance test suite) is used to benchmark JavaScript
        engines' conformity to the ECMAScript standard.
      </p>
    </section>

    <section class="ms-section">
      <h2>What is tested?</h2>
      <p>
        mscts checks what a server sends to a player, and compares it with
        what vanilla sends. Today it covers:
      </p>
      <ul>
        <li>
          The server list: the description, player count and ping a player
          sees before joining.
        </li>
        <li>
          Changing blocks with <code>/setblock</code>, <code>/fill</code> and
          <code>/clone</code>: the blocks that change, the items they drop,
          and the server's reply.
        </li>
      </ul>
      <p>
        The next planned changes are related to world joining. Redstone and
        random mechanics are planned after that.
        <a :href="withBase('/reference/groups')">See everything mscts checks today.</a>
      </p>
    </section>

    <section class="ms-section">
      <h2>How it works</h2>
      <p>
        mscts starts a vanilla Minecraft server alongside the custom server
        you're testing. The custom server requires an mscts Adapter, a small
        module that writes its configuration so it starts with the same
        settings and the same world as vanilla
        (<a :href="withBase('/guide/writing-an-adapter')">read more about Adapters</a>).
      </p>
      <p>
        With everything set up, mscts connects to each server as a player,
        performs the same actions on both, and records every message each
        server sends back. It never reads either server's code, so it works
        the same for a server written in Rust, Java or anything else. Finally
        it compares the two recordings field by field. Each field is a test
        case, named after its message and the field, such as
        <code>status_response.description</code>, and mscts lists every one
        where the custom server differs from vanilla.
      </p>
      <p>
        Some mechanics are random, such as mob spawning and loot, so one
        recording cannot show whether two servers behave the same. For
        those, mscts will repeat the same actions many times and compare the
        spread of results. These longer runs are planned and not available
        yet.
      </p>
    </section>

    <section class="ms-section">
      <h2>Roadmap</h2>
      <p>
        Today mscts compares how vanilla and Pumpkin answer the server list,
        and prints a text Report. Bots can join the game; comparing what
        happens in it is next.
      </p>
      <div class="ms-actions ms-cta">
        <a class="ms-button" :href="withBase('/status')">See the project status</a>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { withBase } from "vitepress";
</script>
