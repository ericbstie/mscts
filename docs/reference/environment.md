# Environment variables

| Variable | Used for | Default |
| --- | --- | --- |
| `MSCTS_CACHE` | Where Installations are stored. Must be an absolute path. | `$XDG_CACHE_HOME/mscts`, else `~/.cache/mscts` |
| `XDG_CACHE_HOME` | The base of the default cache, if `MSCTS_CACHE` is unset. Ignored if empty or relative. | `~/.cache` |
| `MSCTS_JAVA` | The Java launcher for vanilla. Minecraft 26.3 requires Java 25. | `java` on `PATH` |

mscts resolves `MSCTS_JAVA` through symlinks and reads the Java version from
the runtime's `release` file. A mise shim has no such file, so point
`MSCTS_JAVA` at the real launcher:

```sh
export MSCTS_JAVA="$(mise where java)/bin/java"
```

Servers do not inherit your environment. The vanilla Adapter launches Java
with `PATH=/usr/bin:/bin` only. The Pumpkin Adapter launches Pumpkin with an
empty environment.
