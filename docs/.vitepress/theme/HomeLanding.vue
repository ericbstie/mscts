<template>
  <div class="ms-home">
    <section class="ms-hero">
      <div>
        <h1>Measure how close your server is to <span>vanilla</span>.</h1>
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
<span class="muted">starting vanilla and pumpkin ...
running status/basic (1 of 5) ...
...</span>

<span class="head">mscts Report</span>
  Reference    vanilla (its status says version "26.3")
  Candidate    pumpkin (its status says version "26.3")
  Target       Minecraft 26.3 (protocol 777)
  Repetitions  5 of each group

2 groups: 2 different in network traffic only. No difference
a player would notice was found.

<span class="head">Network traffic differences</span>
  Server list ping (status)
    status_response: 4 values are sent differently, e.g.
      - json_response.description: vanilla sends "mscts",
        pumpkin sends {"text": "mscts"}
      - json_response.favicon: vanilla leaves it out,
        pumpkin sends null
      <span class="muted">...</span>

<span class="head">Timings (ms)</span>
  measurement       vanilla median  pumpkin median  n
  status.rtt                  1.41            0.27  5
  instance.startup           9,987              39  1</pre>
      </div>
    </section>

    <section class="ms-section">
      <h2>Why use this tool?</h2>
      <p>
        mscts is for people who want a custom server that keeps vanilla's
        behavior. It gives an objective measure of that playability: it lists
        every difference a player on the vanilla client could notice. As a
        player, you can decide whether a server is close enough to vanilla
        for your liking. As a developer, you can focus on performance and new
        features without sacrificing core vanilla compliance.
      </p>
    </section>

    <section class="ms-section">
      <h2>How it works</h2>
      <p>
        mscts starts two servers on your machine: vanilla Minecraft and the
        custom server you want to test. Both run offline, each on its own
        local address, and neither can reach the internet. For each kind of
        server, a small module called an Adapter writes that server's own
        configuration, so both start with the same settings.
      </p>
      <p>
        mscts then connects to each server the way the Minecraft client does,
        performs the same actions on both, and records every message each
        server sends back. It never reads either server's code, so it works
        the same for a server written in Rust, Java or anything else. Finally
        it compares the two recordings field by field and lists every field
        where the custom server differs from vanilla.
      </p>
    </section>

    <section class="ms-section">
      <h2>Gameplay and network traffic test cases</h2>
      <p>
        Two servers can send the same information in different formats, and
        the vanilla client can end up with exactly the same result from
        both. mscts only treats two formats as equal where we have read
        vanilla Minecraft's own decoding code and written down a rule for
        that exact case. Anything without such a rule counts as a gameplay
        difference.
      </p>
      <div class="ms-split">
        <div class="ms-card">
          <span class="ms-tag gameplay">gameplay</span>
          <p>
            The vanilla client ends up with something different, so a player
            could notice it. A missing message, a different player limit in
            the server list, or a server that closes the connection all land
            here.
          </p>
        </div>
        <div class="ms-card">
          <span class="ms-tag network-traffic">network traffic</span>
          <p>
            The servers send the same thing in different formats. Vanilla
            sends its server description as the text <code>"mscts"</code>, and
            Pumpkin sends <code>{"text": "mscts"}</code>. The vanilla client
            reads both as the same text.
          </p>
        </div>
      </div>
    </section>

    <section class="ms-section">
      <h2>What works today</h2>
      <p>
        Today mscts plays the server list tests against vanilla and Pumpkin
        and prints a text Report. Bots can join the game; gameplay tests are
        next.
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
