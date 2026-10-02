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
Running tests against pumpkin
- Server list description  status_response.description
- Unused secure chat flag  status_response.enforceSecureChat
- Server list icon  status_response.favicon
- Server list player sample  status_response.players.sample
Took 22 s</pre>
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
        mscts starts a vanilla Minecraft server alongside the custom server
        you're testing. Both run offline on your machine, and neither can
        reach the internet. The custom server needs an mscts Adapter, a small
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
