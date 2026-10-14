/* Exercise the real SET_PARAMETER handler without advertising any speakers. */
#include <assert.h>
#include <sys/socket.h>
#include "../common/libraop/src/raop_server.c"

log_level raop_loglevel = lERROR, util_loglevel = lERROR;
static int events;
static void callback(void *owner, raopsr_event_t event, ...) {
    (void)owner;
    if (event == RAOP_METADATA || event == RAOP_ARTWORK) events++;
}

static void parameter(raopsr_t *ctx, const char *type, const void *body, size_t length) {
    int fd[2]; char header[512], response[1024];
    assert(!socketpair(AF_UNIX, SOCK_STREAM, 0, fd));
    int n = snprintf(header, sizeof(header), "SET_PARAMETER rtsp://127.0.0.1/test RTSP/1.0\r\nCSeq: 1\r\nContent-Type: %s\r\nContent-Length: %zu\r\n\r\n", type, length);
    assert(send(fd[0], header, n, 0) == n);
    if (length) assert(send(fd[0], body, length, 0) == (ssize_t)length);
    assert(handle_rtsp(ctx, fd[1]));
    assert(recv(fd[0], response, sizeof(response), 0) > 0);
    close(fd[0]); close(fd[1]);
}

int main(void) {
    raopsr_t ctx = {0};
    ctx.raop_cb = callback;
    strcpy(ctx.sender, "Alex's iPhone");
    uint16_t port = 0;
    struct in_addr host = { .s_addr = htonl(INADDR_LOOPBACK) };
    assert(http_pico_init(host, &port, 1));
    /* Wait for the existing pico server's worker to mark itself running. */
    usleep(100000);
    const char png[] = "\x89PNG\r\n\x1a\n";
    parameter(&ctx, "image/png", png, 8);
    assert(ctx.metadata.artwork && strstr(ctx.metadata.artwork, ".png"));
    assert(!strcmp(ctx.metadata.title, "AirPlay from Alex's iPhone"));
    char *first = strdup(ctx.metadata.artwork);
    const char song[] = {'m','i','n','m',0,0,0,4,'S','o','n','g'};
    parameter(&ctx, "application/x-dmap-tagged", song, sizeof(song));
    assert(!strcmp(ctx.metadata.title, "Song"));
    assert(!strcmp(first, ctx.metadata.artwork));
    const char jpg[] = "\xff\xd8\xff";
    parameter(&ctx, "image/jpeg", jpg, 3);
    assert(strstr(ctx.metadata.artwork, ".jpg"));
    assert(strcmp(first, ctx.metadata.artwork));
    parameter(&ctx, "image/none", NULL, 0);
    assert(!ctx.metadata.artwork && !*ctx.artwork_path);
    assert(events == 4);
    clear_artwork(&ctx);
    raopsr_metadata_free(&ctx.metadata);
    free(first);
    http_pico_close();
    puts("RTSP integration passed: PNG/JPEG, sender fallback, track update, artwork replacement/clear");
}
