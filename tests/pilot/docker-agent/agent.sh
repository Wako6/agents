#!/bin/sh
# Agent factice exécuté DANS un conteneur de l'adaptateur docker de pmx (image alpine, busybox, aucune CLI réelle).
#   agent.sh <brief> <comportement>
# Le rapport est la sortie standard (capturée par pmx). Les sondes impriment `PROBE <nom> <OK|FAIL> <détail>` :
# OK = la protection attendue tient. Données exclusivement fictives.
brief="$1"; behavior="$2"
files=$(sed -n '/^## Périmètre/,/^## Vérification/p' "$brief" | sed -n 's/^- `\(.*\)`$/\1/p')
attempt=$(grep -o 'tentative [0-9]*' "$brief" | head -1 | cut -d' ' -f2)
details=$(sed -n 's/^- Détails : //p' "$brief")
probe() { if [ "$2" = 0 ]; then echo "PROBE $1 OK $3"; else echo "PROBE $1 FAIL $3"; fi; }

write_files() {
  for f in $files; do mkdir -p "/work/$(dirname "$f")"; echo "// équipe factice docker ($behavior) $1" > "/work/$f"; done
}

case "$behavior" in
  slow) sleep 3; write_files ;;
  work)  # charge de mesure : ~48 Mo gardés en mémoire + boucle active ~4 s
    x=$(head -c 48000000 /dev/zero | tr '\0' a); end=$(( $(date +%s) + 4 )); while [ "$(date +%s)" -lt "$end" ]; do :; done
    echo "held ${#x}"; write_files ;;
  hang) sleep 300 ;;
  fail) echo "Status: FAILED"; echo "Open blockers: fake failure"; exit 1 ;;
  outside) sleep 1; write_files; echo "hors périmètre" > /work/README.md ;;
  fifo) write_files; mkfifo /work/.hidden-pipe ;;
  symlink) for f in $files; do mkdir -p "/work/$(dirname "$f")"; ln -s /etc/passwd "/work/$f"; done ;;
  oom)  # remplit la mémoire du shell au-delà de la limite du conteneur
    x=$(head -c 400000000 /dev/zero | tr '\0' a); echo "${#x}"; write_files ;;
  cpu)  # boucle active ~3 s, puis preuve de bridage lue dans le cgroup du conteneur
    end=$(( $(date +%s) + 3 )); while [ "$(date +%s)" -lt "$end" ]; do :; done
    write_files
    echo "CPU_MAX $(cat /sys/fs/cgroup/cpu.max)"; grep -E '^nr_throttled|^throttled_usec' /sys/fs/cgroup/cpu.stat | tr '\n' ' '; echo ;;
  forkbomb)  # tente 200 processus ; la limite pids du conteneur doit l'empêcher (le sous-shell meurt au premier refus)
    ( i=0; while [ $i -lt 200 ]; do sleep 4 & i=$((i+1)); echo "$i" > /tmp/spawned; done ) 2>/dev/null
    read -r spawned < /tmp/spawned; read -r pmax < /sys/fs/cgroup/pids.max; read -r peak < /sys/fs/cgroup/pids.peak 2>/dev/null || peak=?
    while read -r k v; do [ "$k" = max ] && refused=$v; done < /sys/fs/cgroup/pids.events
    echo "PIDS_MAX $pmax PIDS_PEAK $peak SPAWNED $spawned FORKS_REFUSED ${refused:-0}"
    wait; write_files ;;
  probe)
    write_files "$(echo "$details" | sed -n 's/.*MARKER=\([A-Za-z0-9-]*\).*/\1/p')"
    # 1. lecture/écriture dans son espace
    first=$(echo "$files" | head -1); [ -w "/work/$first" ] && [ -n "$(cat "/work/$first")" ]; probe rw_own $? "/work/$first"
    # 2. écriture hors de son espace
    for d in / /etc /usr /pmx /agent /work/.git /root /var /opt; do
      ( echo x > "$d/pmx-probe" ) 2>/dev/null; r=$?; [ $r != 0 ]; probe "write_outside:$d" $? "exit=$r"
    done
    ( echo x > /work/.git ) 2>/dev/null; r=$?; [ $r != 0 ]; probe "write_gitfile" $? "exit=$r"
    ( dd if=/dev/zero of=/tmp/fill bs=1M count=200 ) 2>/dev/null; sz=$(du -m /tmp/fill 2>/dev/null | cut -f1); rm -f /tmp/fill
    [ "${sz:-0}" -lt 100 ]; probe tmpfs_limited $? "written=${sz}M"
    ( printf '#!/bin/sh\necho pwn\n' > /tmp/x.sh && chmod +x /tmp/x.sh && /tmp/x.sh ) >/dev/null 2>&1; r=$?; [ $r != 0 ]; probe tmp_noexec $? "exit=$r"
    # 3. fichiers de l'autre équipe, 4. HOME de l'hôte (chemins hôte transmis dans les détails)
    for hp in $(echo "$details" | sed -n 's/.*HOSTPATHS=\([^ ]*\).*/\1/p' | tr ':' ' '); do
      [ ! -e "$hp" ]; probe "hostpath_absent:$hp" $? ""
    done
    other=$(echo "$details" | sed -n 's/.*OTHER=\([A-Za-z0-9-]*\).*/\1/p')
    hits=$(grep -rl "$other" / --exclude-dir=proc --exclude-dir=sys --exclude-dir=dev 2>/dev/null | grep -v '^/pmx/brief.md$' | head -3)
    [ -z "$hits" ]; probe other_team_marker_absent $? "$hits"
    [ ! -e /home ] || [ -z "$(ls -A /home 2>/dev/null)" ]; probe home_empty $? "$(ls -A /home 2>/dev/null | head -3)"
    # 5. secrets : variables d'environnement, fichiers d'identifiants, sockets
    envs=$(env | cut -d= -f1 | grep -v -E '^(HOME|PATH|HOSTNAME|SHLVL|PWD|PMX_BRIEF|PMX_WORK|PMX_MODE|_)$' | tr '\n' ' ')
    [ -z "$envs" ]; probe env_minimal $? "$envs"
    found=$(find / \( -path /proc -o -path /sys \) -prune -o \( -name 'id_rsa*' -o -name 'id_ed25519*' -o -name '.git-credentials' -o -name 'credentials*' -o -name '.netrc' -o -name '*.pem' -o -name 'docker.sock' -o -name 'agent.*.sock' \) -print 2>/dev/null | grep -v '^/etc/ssl\|^/usr/share' | head -5)
    [ -z "$found" ]; probe no_secret_files $? "$found"
    [ ! -e /var/run/docker.sock ] && [ ! -e /run/docker.sock ]; probe no_docker_socket $? ""
    mounts=$(awk '{print $5}' /proc/self/mountinfo | grep -v -E '^/(proc|sys|dev)(/|$)' | sort | tr '\n' ' ')
    [ "$mounts" = "/ /agent /etc/hostname /etc/hosts /etc/resolv.conf /pmx/brief.md /sbin/docker-init /tmp /work /work/.git " ]; probe mounts_expected $? "$mounts"
    # 6. réseau
    ifs=$(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | tr '\n' ' ')
    [ "$ifs" = "lo " ]; probe net_only_loopback $? "$ifs"
    ( wget -q -T 2 -O /dev/null http://1.1.1.1 ) 2>/dev/null; r=$?; [ $r != 0 ]; probe net_egress_blocked $? "exit=$r"
    ( wget -q -T 2 -O /dev/null http://host.docker.internal:2375/version ) 2>/dev/null; r=$?; [ $r != 0 ]; probe docker_api_unreachable $? "exit=$r"
    # 7. privilèges
    [ "$(id -u)" != 0 ]; probe non_root $? "uid=$(id -u)"
    grep -q '^NoNewPrivs:[[:space:]]*1' /proc/self/status; probe no_new_privs $? ""
    grep -q '^CapEff:[[:space:]]*0000000000000000' /proc/self/status; probe no_capabilities $? "$(grep CapEff /proc/self/status)"
    mkdir -p /tmp/m; ( mount -t tmpfs none /tmp/m ) 2>/dev/null; r=$?; [ $r != 0 ]; probe mount_denied $? "exit=$r"
    ( su -c id root ) </dev/null >/dev/null 2>&1; r=$?; [ $r != 0 ]; probe su_denied $? "exit=$r"
    ( chroot / true ) 2>/dev/null; r=$?; [ $r != 0 ]; probe chroot_denied $? "exit=$r"
    # processus de l'autre équipe : espace de noms pid privé
    n=$(ls /proc | grep -c '^[0-9]*$'); [ "$n" -lt 20 ]; probe pid_namespace_private $? "procs=$n"
    # liens symboliques : cible hors montage inaccessible depuis le conteneur
    hosthome=$(echo "$details" | sed -n 's/.*HOSTPATHS=[^:]*:\([^:]*\).*/\1/p')
    ln -s "$hosthome" /tmp/.lnk 2>/dev/null; ( ls /tmp/.lnk/ ) >/dev/null 2>&1; r=$?; rm -f /tmp/.lnk; [ $r != 0 ]; probe symlink_to_host_dead $? "$hosthome exit=$r"
    echo "LIMITS mem=$(cat /sys/fs/cgroup/memory.max) pids=$(cat /sys/fs/cgroup/pids.max) cpu=$(cat /sys/fs/cgroup/cpu.max)" ;;
  gwprobe|gwwork|gwquota|gwexpire)  # équipe derrière la passerelle pmx (services amont SIMULÉS, jetons fictifs)
    req() {  # nom chemin [fichier POST] [jeton]
      tok=${4-$PMX_GATEWAY_TOKEN}
      if [ -n "$3" ]; then out=$(wget -q -S -T 8 -O /tmp/body --header "x-api-key: $tok" --header "content-type: application/json" --post-file "$3" "$PMX_GATEWAY_URL$2" 2>&1)
      else out=$(wget -q -S -T 8 -O /tmp/body --header "x-api-key: $tok" "$PMX_GATEWAY_URL$2" 2>&1); fi
      code=$(echo "$out" | sed -n 's/.*HTTP\/1\.[01] \([0-9][0-9][0-9]\).*/\1/p' | tail -1)
      echo "GW $1 ${code:-ERR} $(head -c 100 /tmp/body 2>/dev/null | tr -d '\n')"; rm -f /tmp/body
    }
    raw() {  # nom requête brute envoyée à la passerelle sans client HTTP (URI absolue, CONNECT)
      r=$(printf "$2" | nc -w 3 pmx-gateway 8080 2>&1 | head -1 | tr -d '\r'); echo "GW $1 $(echo "$r" | cut -d' ' -f2) $r"
    }
    direct() {  # nom URL : accès direct sans passerelle (doit échouer)
      ( wget -q -T 3 -O /dev/null "$2" ) >/dev/null 2>&1; echo "GW $1 $([ $? = 0 ] && echo REACHED || echo BLOCKED)"
    }
    route=$(echo "$details" | sed -n 's/.*ROUTE=\([a-z]*\).*/\1/p'); other=$(echo "$details" | sed -n 's/.*OTHER=\([a-z]*\).*/\1/p')
    path=$( [ "$route" = openai ] && echo /openai/v1/responses || echo /anthropic/v1/messages )
    opath=$( [ "$other" = openai ] && echo /openai/v1/responses || echo /anthropic/v1/messages )
    echo '{"model":"mock","input":"tâche fictive","messages":[{"role":"user","content":"fictif"}]}' > /tmp/req.json
    write_files
    case "$behavior" in
      gwwork) req own_route "$path" /tmp/req.json; sleep 3; req own_route_2 "$path" /tmp/req.json ;;
      gwquota) for i in 1 2 3 4 5; do req "quota_$i" "$path" /tmp/req.json; done ;;
      gwexpire) req before_expiry "$path" /tmp/req.json; sleep 10; req after_expiry "$path" /tmp/req.json ;;
      gwprobe)
        req own_route "$path" /tmp/req.json
        req other_team_route "$opath" /tmp/req.json
        req unknown_route /evil/x
        req private_network /intranet/v1/x
        req cloud_metadata /metadata/latest/meta-data
        req docker_api /dockerapi/version
        req loopback /loopback/x
        req redirect "/$route/redirect"
        req unknown_token "$path" /tmp/req.json pmxgw_0000000000000000000000000000000000000000000000
        req no_token "$path" /tmp/req.json ""
        head -c 100000 /dev/zero | tr '\0' a > /tmp/big.json; req too_large "$path" /tmp/big.json
        req upstream_slow "/$route/slow"
        req upstream_big "/$route/big"
        raw absolute_uri 'GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n'
        raw connect 'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n'
        direct internet http://1.1.1.1/
        direct mock_upstream_direct http://mock-anthropic:8081/v1/messages
        direct docker_host_api http://host.docker.internal:2375/version
        direct metadata_direct http://169.254.169.254/latest/meta-data
        echo "ENV_TOKEN_VARS $(env | cut -d= -f1 | grep -E 'TOKEN|KEY' | sort | tr '\n' ' ')"
        echo "ENV_UPSTREAM_KEY_VISIBLE $(env | grep -c FAKE-UPSTREAM)" ;;
    esac ;;
  *) write_files ;;
esac
echo "Work item | Role developer"
echo "Status: DONE"
echo "Files touched: $files"
echo "Evidence: fake docker agent ($behavior), attempt ${attempt:-?}"
