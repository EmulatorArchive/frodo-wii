#include <unistd.h> /* unlink */

#include "menu.hh"
#include "file_browser.hh"
#include "game_info.hh"
#include "game_info_box.hh"
#include "utils.hh"

static const char *game_exts[] = {".d64", ".D64", ".t64", ".T64",
	".prg",".PRG", ".p00", ".P00", NULL};
static const char *prg_exts[] = {".prg",".PRG", ".p00", ".P00", NULL};

class DiscMenu;

class DiscView : public GuiView
{
public:
	DiscView();

	~DiscView();

	void pushEvent(SDL_Event *ev);

	void loadGameInfo(const char *what);

	void setDirectory(const char *path);

	/* Inherited */
	void runLogic();

	void draw(SDL_Surface *where);

	DiscMenu *menu;
	GameInfoBox *gameInfo;
};


class DiscMenu : public FileBrowser, TimeoutHandler
{
	friend class DiscView;

public:
	DiscMenu(Font *font) :
		FileBrowser(game_exts, font), TimeoutHandler()
	{
	}

	~DiscMenu()
	{
	}

	virtual void selectCallback(int which)
	{
		const char *fileName = this->pp_msgs[this->cur_sel];
                const char *save_game = strrchr(fileName, '/');

                if (!save_game)
                        save_game = fileName;
                else
                        save_game = save_game + 1; /* Skip '/' */
                strncpy(Gui::gui->np->DrivePath[0], fileName, sizeof(Gui::gui->np->DrivePath[0]));

                if (ext_matches_list(fileName, prg_exts)) {
                	char tmp_filename[255];
                        FILE *src, *dst;

                        snprintf(tmp_filename, sizeof(tmp_filename), "%s/a", Gui::gui->tmp_path);

                        /* Clean temp dir first (we only want one file) */
                        unlink(tmp_filename);

                        src = fopen(Gui::gui->np->DrivePath[0], "r");
                        if (src != NULL)
                        {
                                snprintf(Gui::gui->np->DrivePath[0], sizeof(Gui::gui->np->DrivePath[0]),
                                		"%s", Gui::gui->tmp_path);

                                /* Special handling of .prg: Copy to TMP_PATH and
                                 * load that as a dir */
                                dst = fopen(tmp_filename, "w");
                                if (dst)
                                {
                                        Uint8 buf[1024];
                                        size_t v;

                                        do {
                                                v = fread(buf, 1, sizeof(buf), src);
                                                fwrite(buf, 1, v, dst);
                                        } while (v > 0);
                                        fclose(dst);
                                }
                                fclose(src);
                        }
                }

		Gui::gui->timerController->disarm(this);
		Gui::gui->dv->loadGameInfo(fileName);

		if (Gui::gui->dv->gameInfo->gi)
			Gui::gui->updateGameInfo(Gui::gui->dv->gameInfo->gi);
		else
			Gui::gui->updateGameInfo(new GameInfo(fileName));
		Gui::gui->popView();
	}

	virtual void hoverCallback(int which)
	{
		Gui::gui->timerController->arm(this, 100);
	}

	virtual void timeoutCallback()
	{
		printf("Hovering timed out over %s\n",
				this->pp_msgs[this->cur_sel]);
		Gui::gui->dv->loadGameInfo(this->pp_msgs[this->cur_sel]);
	}

	virtual void escapeCallback(int which)
	{
		Gui::gui->timerController->disarm(this);
		Gui::gui->popView();
	}
};


DiscView::DiscView() : GuiView()
{
	this->menu = new DiscMenu(Gui::gui->default_font);
	this->gameInfo = new GameInfoBox(Gui::gui->default_font);
}

DiscView::~DiscView()
{
	delete this->menu;
	delete this->gameInfo;
}

void DiscView::loadGameInfo(const char *what)
{
	this->gameInfo->loadGameInfo(what);
}

void DiscView::setDirectory(const char *path)
{
	this->menu->setDirectory(path);
}

void DiscView::runLogic()
{
	this->menu->runLogic();
}

void DiscView::pushEvent(SDL_Event *ev)
{
	this->menu->pushEvent(ev);
}

void DiscView::draw(SDL_Surface *where)
{
	SDL_Rect dst;

	/* Blit the backgrounds */
	dst = (SDL_Rect){20,45,300,400};
	SDL_BlitSurface(Gui::gui->main_menu_bg, NULL, where, &dst);

	dst = (SDL_Rect){350,13,0,0};
	SDL_BlitSurface(Gui::gui->disc_info, NULL, where, &dst);

	this->menu->draw(where, 50, 70, 280, 375);
	this->gameInfo->draw(where, 360, 55, 262, 447);
}