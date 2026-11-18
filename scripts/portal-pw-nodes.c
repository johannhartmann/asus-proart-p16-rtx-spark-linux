/* Enumerate nodes visible on a camera portal's PipeWire remote. */
#include <pipewire/pipewire.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct state {
    struct pw_main_loop *loop;
    int sync_seq;
};

static void on_global(void *data, uint32_t id, uint32_t permissions,
                      const char *type, uint32_t version,
                      const struct spa_dict *props)
{
    (void)data; (void)version;
    if (!props || strcmp(type, PW_TYPE_INTERFACE_Node) != 0)
        return;
    const char *name = spa_dict_lookup(props, PW_KEY_NODE_NAME);
    const char *serial = spa_dict_lookup(props, PW_KEY_OBJECT_SERIAL);
    const char *media = spa_dict_lookup(props, PW_KEY_MEDIA_CLASS);
    printf("%u\t%s\t%s\t%s\t%u\n", id, serial ? serial : "",
           name ? name : "", media ? media : "", permissions);
}

static void on_done(void *data, uint32_t id, int seq)
{
    struct state *state = data;
    if (id == PW_ID_CORE && seq == state->sync_seq)
        pw_main_loop_quit(state->loop);
}

static const struct pw_registry_events registry_events = {
    PW_VERSION_REGISTRY_EVENTS, .global = on_global
};
static const struct pw_core_events core_events = {
    PW_VERSION_CORE_EVENTS, .done = on_done
};

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    int fd = atoi(argv[1]);
    pw_init(&argc, &argv);
    struct state state = {0};
    state.loop = pw_main_loop_new(NULL);
    struct pw_context *context = pw_context_new(pw_main_loop_get_loop(state.loop), NULL, 0);
    struct pw_core *core = pw_context_connect_fd(context, fd, NULL, 0);
    if (!core) return 3;
    struct spa_hook core_listener, registry_listener;
    pw_core_add_listener(core, &core_listener, &core_events, &state);
    struct pw_registry *registry = pw_core_get_registry(core, PW_VERSION_REGISTRY, 0);
    pw_registry_add_listener(registry, &registry_listener, &registry_events, &state);
    state.sync_seq = pw_core_sync(core, PW_ID_CORE, 0);
    pw_main_loop_run(state.loop);
    pw_proxy_destroy((struct pw_proxy *)registry);
    pw_core_disconnect(core);
    pw_context_destroy(context);
    pw_main_loop_destroy(state.loop);
    pw_deinit();
    return 0;
}
